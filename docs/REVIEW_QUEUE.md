# Review Queue — manual-testing + product-review checklist

> The running log of everything shipped during the autonomous run that needs your eyes.
> Walk this top-to-bottom during the full manual-test / product-review pass. The codebase
> is green and merged at every step; this is about the things automated checks **can't**
> prove.

## How each item is verified

- **Automated, every PR (gates the merge):** `pytest` (full suite), `ruff`, the
  route/action/capability **auth-matrices**, OpenAPI/route parity, SAST (bandit/semgrep) +
  secret-scan (gitleaks), hash-pinned deps.
- **Scratch simulation (where possible):** I also boot the app and hit real endpoints — and
  load HUD pages headless in a real browser (Chromium/Playwright) — in a throwaway scratch
  dir (never committed) to catch obvious runtime bugs. Noted per item.
- **⚠️ NEEDS YOU:** real LLM / real channel / live HUD pixels / GPU / owner secrets — the
  things only a human + real hardware can confirm.

## Owner-only — I cannot do these (also in `docs/OWNER_TASKS.md`)

- GPU runs — 0.18 Howard fine-tune / speculative decoding.
- Publishing — PyPI / Docker / GPG-signing (your secrets).
- Recruiting design partners; GitHub settings (branch protection, CodeQL enablement).

## Conventions

- **Risky/new behavior ships behind a default-off flag** (e.g. `JARVIS_ACTION_KERNEL`) so it
  changes nothing at runtime until you enable it during testing.

---

## Items (newest first)

### H23.17 — a11y (WCAG) gate on the live HUD ✅ (axe-core, 0 violations baseline)
- **What:** `frontend/e2e/a11y.spec.ts` runs **`@axe-core/playwright`** against the *live* cockpit **and** the
  cinema overlay in real Chromium (the same lane as the E2E harness). It checks the WCAG 2.0/2.1 A/AA rules
  jsdom can't — **real computed colour-contrast, ARIA/role correctness, focus-order, landmark structure** on the
  actually-painted DOM. The gate fails on the unambiguous-bug impacts (**critical/serious**); the full per-impact
  violation list (incl. moderate/minor advisories) is written to `e2e/artifacts/a11y-{cockpit,cinema}.json` as the
  audit trail, so the advisory backlog stays visible without blocking the lane.
- **Result:** the hand-ported HUD is **clean — 0 violations at *every* impact level** (critical/serious/moderate/
  minor) on both the cockpit and the cinema overlay. The gate now guards against an a11y regression slipping in.
- **Verified (automated, in-env):** `npm run e2e` a11y specs → **2/2 passed** booting the real backend + real
  Chromium; `tsc --noEmit` clean; `npm run build` bundle unchanged (purely additive — new spec + axe devDep).
  Joins the existing non-blocking `e2e.yml` CI lane automatically (no workflow change).
- **⚠️ Needs you — nothing blocking:** if you want a deeper pass, a screen-reader walkthrough (NVDA/VoiceOver) of
  the Console panels is the human-only check axe can't do. Otherwise this is done.

### H23.17 — Playwright E2E harness — and it PROVED the Neural Mesh renders ✅ (closes the pixel gap)
- **What:** a real-browser E2E lane for the HUD. `frontend/playwright.config.ts` boots the **real backend**
  (`serve.py` on a loopback test port) and `frontend/e2e/hud.spec.ts` drives the served `/v2` bundle in
  headless Chromium. Two specs: (1) the HUD mounts, the **Neural-Mesh canvas paints non-blank pixels**
  (read from the canvas backing store — the proof jsdom/vitest *cannot* give), and no uncaught page error;
  (2) cinema mode (`m`) opens the full-bleed mesh and **Esc** closes it. Screenshots saved as artifacts.
- **🎉 This resolves the two ⚠️PIXELS items below (PR 20 mesh + PR 21 cinema).** I ran it here and reviewed
  the screenshots: **the mesh renders correctly** — arc-reactor core, the tier-coloured agent constellation
  (Friday/Pepper/Frigga/Hercules/Gecko/Gemini/Ultron/Vision…), the model shell (GEMMA/GEMINI/CLAUDE), comet
  token-flow — and **cinema mode** shows the full-bleed brain with the real footer **"13 agents live · 100%
  on-device"** (the honesty contract working — real %-local, not the prototype's fabricated 87%). You can
  still eyeball it live, but it's no longer unverified.
- **Verified (automated, in-env):** `npm run e2e` → **2/2 passed** booting the real backend (24/24
  components, 17 agents) + real Chromium; `tsc --noEmit` clean (e2e specs typecheck; vitest scope
  unaffected — `.spec.ts` ≠ vitest's `src/**/*.test.tsx`). Non-blocking CI lane added
  (`.github/workflows/e2e.yml`, installs Chromium + boots the backend) so it can stabilise before gating.
- **⚠️ Needs you — nothing blocking:** if you want, download the `hud-e2e-artifacts` from the CI run to see
  the cockpit + cinema screenshots. Otherwise this is done.

### HUD-v3 PR 21 (Phase D) — Cinema mode (the shareable mesh demo) ⚠️ PIXELS
- **What:** the handover §4 "shareable artifact." `CinemaMesh` (in `shell.tsx`) is a **full-bleed
  presentation of the Neural Mesh** (reuses `NeuralMesh` with `cinema=true`) with brand chrome (reactor +
  JARVIS wordmark + rotating taglines) and a live status footer. Toggled by the **`m`** hotkey (overlays
  own the keyboard while open); **Esc** or the corner button exits. Built on PR 20's mesh, so it adds no
  new canvas risk.
- **Honesty contract enforced (notable):** the prototype hardcoded **"87% on-device / 0 cloud leaks /
  EGRESS SEALED"** — the port shows **only real figures**: the live-agent count (from the roster) and the
  **real %-local** (from `/api/analytics/locality`, passed as `localPct`), and **omits the %-local line
  entirely when it's unknown**. No fabricated split makes it onto the shareable artifact.
- **Verified (automated, in-env):** `tsc --noEmit` exit 0; new `cinema.test.tsx` (+4: chrome + embedded
  mesh mount · shows real live-count & %-local and **asserts the fabricated "0 cloud leaks / EGRESS SEALED"
  are absent** · %-local omitted when null · Esc **and** the exit button both fire `onExit`). Full vitest
  **132/132** green; `npm run build` refreshed the served bundle, stale-bundle guard reproducible. No
  backend/route change → parity untouched.
- **⚠️ NEEDS YOU — pixels (with the mesh):** press **`m`** in the HUD; confirm the cinema overlay fills the
  screen, the mesh animates centered, the taglines rotate, the footer shows your real live-count/%-local,
  and Esc exits cleanly. (Same canvas as PR 20 — if the mesh pixels are right, cinema is too.)

### HUD-v3 PR 20 (Phase D) — native Neural Mesh canvas (drops the /brain iframe) ⚠️ PIXELS
- **What:** the signature visual. `frontend/src/mesh.tsx` (`NeuralMesh`) is a **faithful TS port** of the
  designer's `docs/design/hud-v3/v3-mesh.jsx`, now rendered in the cockpit **in place of the
  `/brain?embed=1` iframe** (dropped, per handover §3.5). Arc-reactor core · cost-sized model shell ·
  tier-coloured agent constellation that slowly rotates · comet token-flow on attribution edges ·
  auto-choreographed cascades so it's alive on camera. It reacts to **live agent statuses** (active agents
  emit ambient comet-flow). The `.nmesh*` CSS was ported into `styles.css`.
- **Behaviour-preserving changes from the prototype:** added a **null-2D-context guard** + a
  ResizeObserver guard so it degrades cleanly headless and never throws; dropped the mock
  `window.JarvisMock.streamSub` pulse hook (production has no mock — the mesh stays alive via choreography
  + agent-status). *Wiring explicit pulses to a real SSE stream is a follow-up for when such an endpoint
  exists.*
- **Verified (automated, in-env):** `tsc --noEmit` exit 0; new `mesh.test.tsx` (+3: mounts and renders the
  `.nmesh` wrapper/canvas/legend · **runs a real draw frame against a stubbed 2D context** (setTransform +
  arc called) · degrades cleanly when `getContext` returns null). Full vitest **128/128** green;
  `npm run build` succeeds and refreshed the served bundle (the iframe→canvas swap compiles clean),
  stale-bundle guard reproducible. The `/brain` backend route is untouched → parity green.
- **⚠️⚠️ NEEDS YOU — THE PIXELS (this is the one you offered to check):** open the cockpit and look at the
  NEURAL MESH panel against a running backend. Confirm: the brain renders (not a blank/black panel), the
  core + agent nodes + comet flow animate, hovering a node shows its tooltip, clicking an agent focuses it,
  and `prefers-reduced-motion` calms it. Headless tests prove it *mounts and draws without crashing* — only
  your eyes can confirm it *looks right*. If anything's off, tell me what and I'll fix it fast.

### HUD-v3 PR 19 — Oracle truth-sync panel (the last cleanly-surfaceable endpoint)
- **What:** the Oracle bridge keeps the repo's "truth" docs synced from GitHub and flags local/remote
  conflicts, but had no UI. New `OraclePanel` (in `gap.tsx`, Interop cluster) shows the watcher status +
  last-checked SHA (`GET /api/oracle/status`), lists conflicts (file + resolved/conflict state), and offers
  **sync now** (`POST /api/oracle/sync`) + **clear resolved** (`POST /api/oracle/conflicts/resolve`).
  Honest "in sync · no conflicts" empty state.
- **Verified (automated, end-to-end in-env):** `tsc --noEmit` exit 0; new `oracle-panel.test.tsx` (+3:
  lists a conflict + watcher status · sync-now POSTs · in-sync empty state) — full vitest **125/125** green;
  `npm run build` refreshed the served bundle, stale-bundle guard reproducible. No backend/route change →
  parity untouched.
- **⚠️ Needs you — live pixels:** Console → Interop → ORACLE SYNC; confirm the status + any conflicts read
  right and sync-now triggers a real check (niche dev/ops surface — low-risk, read + sync).
- **Note:** with this, **every cleanly-surfaceable backend endpoint now has a Console UI**. What remains is
  visual-only (Neural-Mesh canvas), secrets/hardware-gated (SaaS connectors, GPU), needs-a-richer-UI (coach
  study mode), or a greenfield product-steer — none of which is a clean autonomous wire-up.

### HUD-v3 PR 18 (B1+++) — interrupt budget in the Decision Inbox (calm by the numbers)
- **What:** surfaces the **interrupt budget** (`GET /autonomy/interrupts` — the MOONSHOT §5.4 "≤N proactive
  pushes/day" guardrail) right in the Decision Inbox header: *"N awaiting you · used/per_day interrupts
  today."* PR 0 shipped this endpoint with no UI; the Observe meter shows an aggregate, but this puts the
  *live remaining headroom* where you actually triage decisions. Default-safe: if no budget is configured
  (`per_day` null) the header just omits it.
- **Why:** the calm-by-the-numbers promise made visible at the point of use — you see both the decisions
  waiting *and* how many more times Jarvis may interrupt you today before it batches the rest.
- **Verified (automated, end-to-end in-env):** `tsc --noEmit` exit 0; `decision-inbox-panel.test.tsx` grew
  +1 (now 8): the header renders `used/per_day interrupts today`. Full vitest **122/122** green;
  `npm run build` refreshed the served bundle, stale-bundle guard reproducible. No backend/route change →
  parity untouched.
- **⚠️ Needs you — live pixels:** confirm the Decision Inbox header shows the budget and that it decrements
  as Jarvis pushes proactive decisions through the day (needs `autonomy.budget` configured).

### HUD-v3 PR 17 (B1++) — Decision Inbox dry-run preview (see consequences before approving)
- **What:** the safest possible north-star affordance — a **preview** button on each blocked decision that
  fetches the **dry-run** (`GET /api/autonomy/tasks/{id}/preview`, H12.5) and renders the consequences
  inline *before* you accept: the **summary**, an **irreversible** flag (red), **would-execute / would-queue**,
  and the first few **effects**. The blueprint's B1 acceptance always called for this preflight; now it's
  there. Toggling it again hides it; it never blocks the accept/edit/reject/defer controls.
- **Why:** completes the north-star's safety story — you can *look before you leap* on a tier-3 irreversible
  action (e.g. a payment) instead of approving blind.
- **Verified (automated, end-to-end in-env):** `tsc --noEmit` exit 0; `decision-inbox-panel.test.tsx` grew
  +1 (now 7): preview GETs `…/{id}/preview` and shows the summary + `irreversible` + `would queue` + an
  effect. Full vitest **121/121** green; `npm run build` refreshed the served bundle, stale-bundle guard
  reproducible. No backend/route change → parity untouched.
- **⚠️ Needs you — live pixels:** queue a tier-3 (e.g. payment) decision, click **preview**, and confirm
  the dry-run consequences match what the action would actually do before you accept.

### HUD-v3 PR 16 — Security Skills browser (the 0.42 ATT&CK pack, now visible)
- **What:** the 0.42 Security Skills pack (curated, offline ATT&CK / D3FEND / NIST CSF knowledge) had a
  full read-only API but **no UI**. New `SecuritySkillsPanel` (in `gap.tsx`, Trust cluster) browses the
  **ATT&CK tactics** (`GET /api/security-skills/tactics`), each expandable to its **curated techniques**
  (`GET /api/security-skills/techniques?tactic=`). Read-only, user-guarded; nothing fabricated (the pack
  carries its own DISCLAIMER + SOURCES).
- **Verified (automated, end-to-end in-env):** `tsc --noEmit` exit 0; new `security-skills-panel.test.tsx`
  (+2: lists a tactic · expanding it GETs `…/techniques?tactic=TA0001` and shows the technique) — full
  vitest **120/120** green; `npm run build` refreshed the served bundle, stale-bundle guard reproducible.
  No backend/route change → parity untouched.
- **⚠️ Needs you — live pixels:** Console → Trust → SECURITY SKILLS; confirm the tactic list renders and
  expanding one shows its techniques (it's a reference browser — low-risk, read-only).

### HUD-v3 PR 15 (B1+) — Decision Inbox `edit` action (completes the 4 decision options)
- **What:** the Decision Inbox (PR 12) shipped accept/reject/defer but not **edit** — the backend's 4th
  action (`apply_decision`), which lets you *modify a proposed action's payload before approving* (e.g.
  change a payment amount). Added an **edit** control to `DecisionInboxPanel`: it reveals an inline editor
  pre-filled with the task's `payload` as JSON; **save & approve** → `POST /autonomy/tasks/{id}/decision
  {action:"edit", payload}` (the backend re-gates the edited payload — BUG-11 — so a riskier edit stays
  blocked for re-approval). Invalid JSON is a no-op (won't submit).
- **Why:** completes the north-star's full decision vocabulary — you can now tune a risky proposal down to
  something you'll accept instead of an all-or-nothing reject.
- **Verified (automated, end-to-end in-env):** `tsc --noEmit` exit 0; `decision-inbox-panel.test.tsx` grew
  +2 (now 6): edit reveals the payload JSON and **save POSTs `{action:"edit", payload}`** with the edited
  value · **invalid JSON does not POST**. Full vitest **118/118** green; `npm run build` refreshed the
  served bundle, stale-bundle guard reproducible. No backend/route change → parity untouched.
- **⚠️ Needs you — live pixels:** queue a tier-2/3 decision, click **edit**, change a payload field, hit
  save & approve, and confirm the edited action runs (or, if your edit raised the risk, that it correctly
  stays blocked for re-approval — the BUG-11 re-gate).

### HUD-v3 PR 14 — Mic Satellites pairing flow (handover §4.4)
- **What:** the H12.8 satellite hub ("pair a phone/device as a mic satellite" → shared-GPU inference) had
  no UI — pairing was a stub. New `SatellitesPanel` (in `gap.tsx`, Interop cluster) lists paired satellites
  (id + kind) via `GET /api/satellites`, **pairs** a device (`POST /api/satellites/register {satellite_id}`),
  and **unpairs** one (`DELETE /api/satellites/{id}`). All user-guarded.
- **Verified (automated, end-to-end in-env):** `tsc --noEmit` exit 0; new `satellites-panel.test.tsx` (+3:
  lists a paired device with its kind · pair POSTs `{satellite_id}` only when an id is given · unpair
  DELETEs) — full vitest **116/116** green; `npm run build` refreshed the served bundle, stale-bundle guard
  reproducible. No backend/route change → parity untouched.
- **⚠️ Needs you — live pixels + a real device:** Console → Interop → MIC SATELLITES; pair a phone/device
  (needs the companion satellite client) and confirm it registers + can dispatch to the shared inference
  rail, then unpair it.

### HUD-v3 PR 13 — Ambient Capture stream (the privacy promise made visible)
- **What:** the opt-in passive-capture backend (clipboard/browser/screenshot → KG, redacted, local) had
  no UI. New `CapturePanel` (in `gap.tsx`, Memory cluster) shows the capture status (on/off + count) and
  the captured stream — each item rendered as its **redacted `preview`** (never raw content), **individually
  deletable** (`DELETE /api/capture/{id}`), with a **clear all** (`POST /api/capture/clear`). This is the
  on-brand "the privacy promise made visible" surface from the handover's competitive backlog (§4.3).
- **Verified (automated, end-to-end in-env):** `tsc --noEmit` exit 0; new `capture-panel.test.tsx` (+4:
  shows a redacted preview + its surface · ✕ DELETEs a single item · clear-all POSTs · honest empty-state) —
  full vitest **113/113** green; `npm run build` refreshed the served bundle, stale-bundle guard
  reproducible. No backend/route change → parity untouched.
- **⚠️ Needs you — live pixels + the privacy loop:** enable a capture surface, let it capture something,
  open Console → Memory → AMBIENT CAPTURE, confirm only the redacted preview shows (not raw content), then
  delete one item and clear-all and confirm they're gone (the deletable-privacy promise).

### HUD-v3 PR 12 (B1) — the DECISION INBOX (the north-star resolve action)
- **What:** the most important interaction in the product, and it was **genuinely missing a control**.
  The HUD *read* the autonomy queue (`/tasks`, drawn as a network fan + a count) but had **no way to
  resolve a blocked decision**. New `DecisionInboxPanel` (in `gap.tsx`, Autonomy & Agents cluster — placed
  **first**) reads the blocked queue (`GET /autonomy/tasks?status=blocked`, admin) and resolves each via
  **accept / reject / defer** → `POST /autonomy/tasks/{id}/decision {action}` (admin), with a per-decision
  risk-tier chip (tier 3 = red) and an honest **"all clear · no decisions waiting"** empty state.
- **Why it matters / how it was missed:** the blueprint had over-optimistically marked B1 "exists" because
  the queue was visualized — but visualization ≠ the north-star *action*. A final sweep of every mutating
  route against the frontend caught that `POST /autonomy/tasks/{id}/decision` was referenced **nowhere** in
  `frontend/src`. This PR closes it.
- **Verified (automated, end-to-end in-env):** `tsc --noEmit` exit 0; new `decision-inbox-panel.test.tsx`
  (+4: shows a blocked decision with its risk tier · ✓ POSTs `{action:"accept"}` to `…/{id}/decision` · ✕
  POSTs `{action:"reject"}` · honest all-clear empty state) — full vitest **109/109** green; `npm run build`
  refreshed the served bundle, stale-bundle guard reproducible. No backend/route change → parity untouched.
- **⚠️ Needs you — live pixels + a real decision (the key end-to-end test):** with autonomy in ASK mode,
  trigger an action that queues a decision (e.g. a tier-2/3 task), open Console → Autonomy & Agents →
  DECISION INBOX (admin token), and confirm accept actually runs it / reject cancels it / defer postpones —
  this is the core proactive loop, worth exercising fully.

### HUD-v3 PR 11 (C3) — Knowledge-Graph entity controls + memory-forget in the Console
- **What:** the Memory cluster had spaces/docs/notes panels but **no knowledge-graph control**. New
  `KgPanel` (in `gap.tsx`, Memory cluster) lists/searches KG entities (`GET /api/kg/entities`) with their
  type + mention count, **deletes** an entity (`DELETE /api/kg/entities/{name}`), and **forgets** a memory
  item by id (`POST /api/memory/decay/forget` — ACT-R decay with transitive dependents). All user-guarded.
- **Verified (automated, end-to-end in-env):** `tsc --noEmit` exit 0; new `kg-panel.test.tsx` (+3: lists
  an entity with type + mention count · ✕ DELETEs the entity · forget POSTs `{id}` only when an id is
  given) — full vitest **105/105** green; `npm run build` refreshed the served bundle, stale-bundle guard
  reproducible. No backend/route change → parity untouched.
- **⚠️ Needs you — live pixels + a real delete/forget:** Console → Memory → KNOWLEDGE GRAPH against a
  running backend; confirm the entity list matches `GET /api/kg/entities`, delete a test entity and confirm
  it's gone, and forget a known memory-item id and confirm it (and its dependents) are purged. (These
  mutate your graph/memory — use a test item.)

### HUD-v3 PR 10 (C7) — Workflow-runtime management panel in the Console
- **What:** the existing `StepGenPanel` covers the AI step-*builder*, but the 0.34 workflow *runtime* had
  no management surface. New `WorkflowsPanel` (in `gap.tsx`, Build cluster) lists registered pipelines
  (built-in + user-defined merged) with a step count via `GET /api/workflows`, **runs** one
  (`POST /api/workflows/run`, user-guard, surfaces a ran/ok message), and **deletes** a user-defined one
  (`DELETE /api/workflows/{id}`, admin).
- **Verified (automated, end-to-end in-env):** `tsc --noEmit` exit 0; new `workflows-panel.test.tsx` (+3:
  lists a pipeline with its step count · run POSTs `{pipeline_id}` and shows the result · ✕ DELETEs the
  pipeline) — full vitest **102/102** green; `npm run build` refreshed the served bundle, stale-bundle
  guard reproducible. No backend/route change → parity untouched.
- **⚠️ Needs you — live pixels + a real run:** Console → Build → WORKFLOWS against a running backend;
  confirm the pipeline list matches `GET /api/workflows`, run one and confirm it executes, and (admin)
  delete a user-defined pipeline and confirm it's gone. (Run fires a real workflow — pick a safe one.)

### HUD-v3 PR 9 (C8) — Model Arena leaderboard + Answer Quality gate in the Console
- **What:** closes C8's two missing Observe surfaces (evals + review already had panels). `ArenaPanel`
  reads `GET /api/arena/leaderboard` and ranks models by **ELO** with win-rate + games (read-only; honest
  "no matches yet" empty-state). `QualityPanel` reads `GET /api/quality` (rolling **avg_score** + alert
  **threshold** + an ALERTING/ok chip) and lets an admin retune the gate via `POST /api/quality/threshold`.
- **Verified (automated, end-to-end in-env):** `tsc --noEmit` exit 0; new `arena-quality-panel.test.tsx`
  (+4: arena ranks models with ELO + win-rate · honest empty-state · quality shows avg/threshold/alert ·
  set-threshold POSTs the new value) — full vitest **99/99** green; `npm run build` refreshed the served
  bundle, stale-bundle guard reproducible. No backend/route change → parity untouched.
- **⚠️ Needs you — live pixels:** Console → Observe → MODEL ARENA + ANSWER QUALITY against a running
  backend; confirm the leaderboard matches `GET /api/arena/leaderboard` and the quality avg/threshold read
  right, and that setting a new threshold takes (admin token).

### HUD-v3 PR 8 (C9 forget-me) — destructive "forget me" completes the data triad
- **What:** adds a **confirm-gated forget-me** control to the BackupPanel (now titled *BACKUP · EXPORT ·
  FORGET*), so the data-sovereignty triad is whole. It mirrors the backend's hard-to-fat-finger design:
  a red **"forget me…"** reveal → type the exact token **`FORGET`** → **"confirm erase"** (disabled until
  the token matches) → `POST /api/admin/forget {confirm:"FORGET"}` (backup-first, recoverable from the
  archive it just made), with a **cancel** path.
- **Safety:** the irreversible action is double-gated — admin token *and* the typed acknowledgement; the
  confirm button can't even fire until the input is exactly `FORGET`.
- **Verified (automated, end-to-end in-env):** `tsc --noEmit` exit 0; backup-panel.test.tsx grew +2 (now
  6): the gate blocks an empty **and** a wrong token (no `/api/admin/forget` call), and only the exact
  `FORGET` token POSTs `{confirm:"FORGET"}`. Full vitest **95/95** green; `npm run build` refreshed the
  served bundle, stale-bundle guard reproducible. No backend/route change → parity untouched.
- **⚠️ Needs you — live pixels + the real purge (CAREFUL):** this erases your content at rest (backup-first).
  On a throwaway/test profile: Console → Admin → BACKUP · EXPORT · FORGET → forget me… → type `FORGET` →
  confirm; verify a fresh snapshot was taken first and the content is gone, then confirm you can restore
  from that snapshot. **Do not run against real data unless you mean it.**

### HUD-v3 PR 7 (C9) — Backup & Export (data-sovereignty controls) in the Console
- **What:** the 0.14/H23.8 backup + H23.9 export backend (consistent SQLite snapshots, restore-drill,
  portable JSON takeout) had **no control surface**. New `BackupPanel` (in `gap.tsx`, Admin cluster) is
  the data-sovereignty front door: lists snapshots (size + `enc` tag for encrypted archives via
  `GET /api/admin/backup`), **back up now** (`POST /api/admin/backup`), **restore-drill verify**
  (`POST /api/admin/backup/verify` → surfaces the OK + file count), and **export my data**
  (`POST /api/admin/export` → reports the written size). All admin-guarded.
- **Why this one:** north-star aligned — "your data, on your machine, yours to take." It makes the backup
  *and the proof it restores* a one-tap operation instead of a CLI-only feature.
- **Verified (automated, end-to-end in-env):** `tsc --noEmit` exit 0; new `backup-panel.test.tsx` (+4:
  lists a snapshot with size + enc tag · back-up-now POSTs · restore-drill POSTs verify and shows the OK ·
  export-me POSTs and reports the size) — full vitest **93/93** green; `npm run build` refreshed the served
  bundle, stale-bundle guard reproducible. No backend/route change → parity untouched.
- **⚠️ Needs you — live pixels + a real backup/restore:** open Console → Admin → BACKUP & EXPORT against a
  running backend (admin token); click **back up now**, confirm a snapshot appears; click **verify**,
  confirm the restore-drill reports OK; click **export my data**, confirm the export is written and the
  size is plausible. (These fire real admin operations on your data root.)

### HUD-v3 PR 6 (C6) — Governance scorecard + Security posture panels in the Console
- **What:** two read-only Trust panels closing C6 (loop-breaker, the third leg, already had a panel).
  `GovernancePanel` reads the **public** trust scorecard `GET /api/security/governance` — per-suite
  scores (injection / harm / OWASP: `passed/n` + %) and the overall **pass/FAIL gate** vs threshold.
  `PosturePanel` reads the admin `GET /api/security/posture` — secrets-at-rest (encrypted + backend),
  skill signing (required? + trusted/total), sandbox isolation, and the guardrails mode. Neither had a
  control surface before.
- **Honesty:** every number is the real suite/registry result; a failing gate shows **"gate: FAIL"** in
  red, not a softened state. No fabricated scores.
- **Verified (automated, end-to-end in-env):** `tsc --noEmit` exit 0; new `governance-posture-panel.test.tsx`
  (+3: governance shows the gate + per-suite scores incl. a partial pass · a FAILED gate is surfaced
  honestly · posture shows secrets/signing/sandbox/guardrails state) — full vitest **89/89** green;
  `npm run build` refreshed the served bundle, stale-bundle guard reproducible. No backend/route change →
  parity untouched.
- **⚠️ Needs you — live pixels:** open Console → Trust → GOVERNANCE SCORECARD + SECURITY POSTURE against a
  running backend (admin token for posture); confirm the suite scores + gate match `GET /api/security/governance`
  and the posture rows reflect your actual config (secrets backend, signing requirement, sandbox).

### HUD-v3 PR 5 (C2) — Per-agent autonomy dial in the Console (closes PR 0's loop)
- **What:** PR 0 (#418) made per-agent **AUTO/ASK/OFF** *enforceable* (`AutonomyPolicy.agent_modes`, the
  kernel threads `action.agent`) but shipped **no UI**. This is that control surface. New
  `AgentAutonomyPanel` (in `gap.tsx`, Autonomy & Agents cluster) reads `GET /autonomy/policy`
  (`{global, agents}`), shows the global mode + each per-agent override (color-coded auto/ask/off), lets
  you **set** an override (agent name + mode select → `POST {agent, mode}`) and **clear** one (✕ →
  `POST {agent, mode:"default"}`, which falls back to global). Admin-guarded; complements the existing
  global `AutonomyMode` in `modes2.tsx`.
- **Why this one:** it completes the story I started this thread with — the backend capability had no
  front door. Now an owner can quiet a single noisy agent (e.g. `vision → off`) while the rest keep
  acting, straight from the Console.
- **Honest empty-state:** with no overrides the panel says *"every agent follows the global mode (<mode>)"*
  rather than implying per-agent config that isn't there.
- **Verified (automated, end-to-end in-env):** `tsc --noEmit` exit 0; new `agent-autonomy-panel.test.tsx`
  (+4: shows global + an override · ✕ clears with `mode=default` · honest empty-state · set POSTs only
  when an agent is named) — full vitest **86/86** green; `npm run build` refreshed the served bundle,
  stale-bundle guard reproducible. No backend/route change → parity untouched.
- **⚠️ Needs you — live pixels + a real effect:** open Console → Autonomy & Agents → PER-AGENT AUTONOMY
  against a running backend (admin token set); set one agent to `off`, confirm it shows, then confirm that
  agent's actions actually escalate to the approval queue while others still act (the PR 0 enforcement),
  and that ✕ returns it to the global mode.

### HUD-v3 PR 4 (C10) — Mesh Peers registry control in the Console
- **What:** the A2A **mesh peer registry** — allowlist a peer, get a one-time shared secret, remove a
  peer — is admin-guarded and had **no control surface** (only the A2A approval *inbox* did). New
  `MeshPeersPanel` (in `gap.tsx`, Interop cluster) lists allowlisted peers with the **masked** secret hint
  (`GET /api/a2a/peers`), removes via `DELETE /api/a2a/peers/{id}`, and adds via `POST /api/a2a/peers` —
  surfacing the shared secret **once** on add, mirroring the backend's return-once contract (the registry
  never re-exposes it).
- **Security-faithful:** the panel never shows a stored secret — only the backend-provided `secret_hint`
  (first 4 chars) for existing peers, and the full secret exactly once at creation. All three calls are
  admin-guarded (in-app token, not `window.prompt`, per the auth-tier rule).
- **Verified (automated, end-to-end in-env):** `tsc --noEmit` exit 0; new `mesh-panel.test.tsx` (+3: lists
  a peer with its masked hint · clicking remove fires a real `DELETE /api/a2a/peers/{id}` · add POSTs only
  when a peer_id is given) — full vitest **82/82** green; `npm run build` refreshed the served bundle,
  stale-bundle guard reproducible. No backend/route change → parity untouched.
- **⚠️ Needs you — live pixels + a real pairing:** open Console → Interop → MESH PEERS against a running
  backend; add a peer and confirm the one-time secret shows, then reload and confirm only the masked hint
  remains; remove it and confirm it's gone. (The add/remove fire real admin routes — needs the admin
  token set.)

### HUD-v3 PR 3 (C1) — Missions board with governed controls in the Console
- **What:** the first **Phase-C write-control**. A new `MissionsPanel` (in `gap.tsx`, Autonomy & Agents
  cluster) surfaces the **0.32 Mission Workspaces** — long-horizon governed work — as a board:
  `GET /api/missions`, each workspace shown with its status (planned/active/paused/done/failed/cancelled),
  step budget (`steps_used/max_steps`), and **contextual action buttons** matching the state machine
  (planned→`start`; active→`pause`/`complete`/`cancel`; paused→`resume`/`cancel`; terminal→none), each
  wired to the real **user-guarded** `POST /api/missions/{id}/{action}` route. The backend + the data-layer
  fetch existed, but there was **no control surface** until now.
- **Why this one:** Missions are the clearest "governed long-horizon work" surface and the endpoints were
  fully built — a pure additive port, no reinterpretation.
- **Verified (automated, end-to-end in-env):** `tsc --noEmit` exit 0; new `missions-panel.test.tsx` (+3:
  lists a workspace with status + budget · the per-status controls are correct (active→pause/complete/
  cancel, paused→resume, done→no buttons) · **clicking a control POSTs to the real `/api/missions/42/pause`
  route**); full vitest **79/79** green; `npm run build` refreshed the served bundle, stale-bundle guard
  reproducible. No backend/route change → parity untouched.
- **⚠️ Needs you — live pixels + a real mission lifecycle:** open Console → Autonomy & Agents → MISSIONS
  against a running backend with at least one mission; confirm the status colors + step budget read right
  and that clicking pause/resume/complete/cancel actually transitions the mission (the buttons fire the
  governed routes — worth confirming the optimistic reload reflects the new state).

### HUD-v3 PR 2 (B3) — Verification Fabric readiness board in the Console
- **What:** the first genuine **frontend gap** from the blueprint's Phase B substrate. A new
  `ReadinessPanel` (in `gap.tsx`, Trust cluster, next to the Action-Kernel meter) renders the capability
  registry — `GET /api/metrics/capabilities` — as the **SEAM→WIRED→VERIFIED→GA** readiness ladder
  (roll-up tags + per-capability state), so "looks done, isn't wired" is a *visible* state. Most of Phase
  B already existed in the production HUD (Decision Inbox, kernel meter, kill-switch, audit-verify,
  %-local); the readiness board was the one substrate surface genuinely **absent**, and it binds an
  endpoint that already ships (V2).
- **Honesty contract enforced:** while no capability is harness-proven (`harness_pending:true`) the panel
  shows an amber **"wired, not yet proven — nothing is VERIFIED until a green reality-harness promotes
  it"** banner instead of implying verification we can't back. The banner disappears the moment a real
  VERIFIED state exists.
- **Verified (automated, end-to-end in this env):** `tsc --noEmit` exit 0; new `readiness-panel.test.tsx`
  (+3: GETs the endpoint + shows the ladder + a capability · the harness-pending banner · the banner is
  **absent** once something is VERIFIED) — full vitest suite **76/76** green; `npm run build` refreshed
  the served `agents/web/v2` bundle and the **stale-bundle guard is reproducible** (a second build is a
  no-op diff). No backend/route change → parity untouched.
- **⚠️ Needs you — the live-pixel render only:** as for every HUD panel (CDX-9), I can prove the wiring +
  the conditional display logic headlessly but **not** the actual rendered pixels. Open the Console → Trust
  section and eyeball the VERIFICATION FABRIC panel against a running backend: confirm the ladder counts
  match `GET /api/metrics/capabilities` and the "not yet proven" banner shows until the reality harness
  promotes something.

### HUD-v3 PR 1 — vendor the prototype (design source of truth) + the impl-blueprint doc
- **What:** lands the two planning anchors for the hud-v3 port. (1) The **executable design spec** is
  vendored into `docs/design/hud-v3/` (22 files: the `v3-*.jsx` prototype + `v3-style.css` + `index.html`
  + the original `HANDOVER_CLAUDE_CODE.md`) — same convention as the existing `docs/design/worldview-mock/`,
  so it sits **outside** the `frontend/` build (no tsc/vitest/eslint touches it). (2) The implementation
  blueprint `docs/design/2026-06-28-hud-v3-impl-blueprint.md` — one row per surface → prototype file →
  target `frontend/src` component → **real** endpoint(s) → acceptance → parity row, sequenced Phase B
  (substrate) → C (~37 write-controls) → D (tail).
- **Why it matters:** the production HUD (`frontend/src`, served at `/v2`) **already exists** — v3 is the
  next design iteration, so the port is an *evolve-in-place*, not a rewrite. The blueprint nails the
  **path-rename ledger**: of everything the prototype binds, only **4** routes need renaming
  (`/autonomy/missions`→`/api/missions`, `/governance`→`/api/security/governance`,
  `/posture`→`/api/security/posture`, `/loop-breaker`→`/api/security/loop-breaker`); every other route is
  already exact (the 2 that weren't shipped in PR 0). Each prototype route already carries a v2 parity
  surface, so the `hud-v2-parity` gate stays green by construction.
- **Verified (automated):** doc-only PR — no code paths touched; full suite + parity unchanged. Reconciled
  every prototype-declared path against the authoritative `tests/_snapshots/route_surface.json`.
- **⚠️ Needs you — read the blueprint before the surface PRs land:** it's the execution contract for PRs
  2…N. Skim `docs/design/2026-06-28-hud-v3-impl-blueprint.md` §2 (the surface table) and confirm the
  Phase-B-first ordering matches what you want to see/test first (Decision Inbox → Kernel table →
  Readiness → kill-switch → audit-verify → %-local). **Known limitation flagged in the doc:** the frontend
  port can't be hermetically runtime/visually verified in this env — `tsc --noEmit` + vitest + the
  stale-bundle guard + this manual checklist are the net.

### HUD-v3 PR 0 — per-agent autonomy policy + interrupt-budget endpoints (backend pre-work)
- **What:** the 2 endpoints the hud-v3 prototype binds that didn't exist yet (the only true backend gap
  in the v3 compatibility review). `GET/POST /autonomy/policy` — per-agent **AUTO/ASK/OFF** overrides (the
  HUD's per-agent autonomy control), and `GET /autonomy/interrupts` — the "calm-by-the-numbers" interrupt
  budget. Per-agent policy is **actually enforced**, not just stored: `AutonomyPolicy` gained
  `agent_modes` + `effective_mode(agent)`, `decide()` resolves the mode per-agent, the kernel threads
  `action.agent` into the policy, and the coordinator resyncs the overrides live each tick.
- **⚠️ Needs you — default-safe, but it's a real control:** with no per-agent override set, **every agent
  behaves exactly as the global mode** (the whole autonomy/kernel suite confirms — zero behavior change).
  Setting e.g. `vision → off` makes only that agent's side-effecting actions wait for approval; `default`
  clears the override. Worth a click-through once the HUD surface lands to confirm the per-agent toggle
  matches your mental model.
- **Verified (automated):** `tests/test_autonomy_per_agent_policy.py` 7 passed (effective_mode fallback;
  per-agent decide; empty-overrides == pure-global; the **kernel threads the agent** so a per-agent `off`
  escalates GRANT→QUEUE while another agent grants; the GET/POST roundtrip + clear; bad-mode 422) + the
  full autonomy/kernel/policy suite (298) green; ruff + bandit clean; route/openapi/auth parity reseeded
  for the 3 new admin routes (hud-v2 already maps `/autonomy/`); STATUS at 3,215 tests / 354 routes.
- **Context:** this is **PR 0** of the hud-v3 port (compatibility review delivered separately). Everything
  else the prototype binds already exists; the remaining v3 work is the frontend port itself (one PR per
  surface, gated by tsc + vitest + the stale-bundle guard) — which needs the runtime/visual env, not this one.

### CDX-7 (action-taint) — the kernel now escalates an action with an untrusted *origin*
- **What:** completes the deferred CDX-7 follow-up at the **kernel** level. `kernel.authorize` already
  escalated a GRANT→QUEUE on a tainted *payload*; it now also escalates when the action's **declared
  `origin`** is an untrusted source (`external` / `inbound` / `channel` / `web` / `rss` / `osint` /
  `worldview`). The real external-HTTP knowledge-graph write already declared `origin="external"` — that
  declaration was previously inert; now the kernel honors it, so an external party's write can't silently
  auto-execute, it's routed to the approval queue (and audited).
- **The honest design call (why it's this and not "full data-flow taint"):** taint **cannot** be propagated
  *through* an LLM — the model launders untrusted content into new text, so there's no reliable flow to
  follow. Rather than ship a half-wired tracker that gives *false* security, the kernel trusts the caller's
  **declared provenance** (`origin`). That's correct and complete for the provenance it's given; callers that
  build actions from untrusted input set `origin` accordingly (the kg-write site does).
- **⚠️ Needs you — nothing, default-safe:** the default `origin="generated"` (an in-house action) is
  trusted, so every normal action is unaffected (the whole kernel suite confirms). This only changes behavior
  for actions explicitly declared to originate from an untrusted source, and even then only when the
  Action Kernel is enabled (`JARVIS_ACTION_KERNEL`, default-off).
- **Verified (automated):** `tests/test_cdx7_action_origin_taint.py` 11 passed (generated→GRANT;
  external/osint/worldview/inbound/channel/web/rss→QUEUE with an "untrusted origin" reason + an approval
  card; tainted-payload regression still escalates and is labelled; taint never overrides a kill-switch
  DENY; and a static guard that the kg-write site keeps declaring `origin="external"`) + the full
  kernel/taint/reality/osint suite (137) green; ruff + bandit clean; no new routes; STATUS at 3,208 tests.

### 0.34 — workflow run-history persistence (opt-in, default-off)
- **What:** workflow **run history** (for the HUD's recent-runs overlay) lived only in an in-memory ring
  (`deque`) and was lost on restart. New `workflows/run_store.py` — a bounded, atomically-written JSON store
  the engine **seeds from** on startup and **records** each run into, so the overlay survives a restart.
  Off by default; `JARVIS_WORKFLOW_PERSIST=1` turns it on.
- **⚠️ Needs you — nothing unless you want durable run history:** with the env unset the engine attaches no
  store (byte-identical behavior). Set `JARVIS_WORKFLOW_PERSIST=1` to persist runs under
  `data/workflows/runs.json` (bounded to the most recent 200, oldest pruned). Noted in `docs/OWNER_TASKS.md`.
- **Verified (automated):** `tests/test_workflow_run_store.py` 11 passed (record→list most-recent-first +
  chronological `all()` for seeding; the cap prunes oldest; missing/corrupt files degrade to empty then stay
  writable; the engine persists on `_stash_run` and seeds `recent()` from the store on init; default = no
  store; env opt-in attaches one; falsey env stays off) + the existing workflow/concurrency suite green;
  ruff + bandit clean; no new routes; STATUS at 3,197 tests.

### 0.31 (cont.) — codeintel search is now an agent-callable MCP tool
- **What:** `codeintel_search` joins the read-only MCP `ROUTE_TOOL_ALLOWLIST`, so an agent can call
  `route_codeintel_search` to locate code symbols — completing the "Code Intelligence **MCP**" half. It rides
  the existing default-off `JARVIS_MCP_ROUTE_TOOLS` kill-switch (so nothing is exposed over MCP unless you
  turn route tools on), and its guard is pinned to `route_auth.json` by the 0.36 parity gate. A shared
  module-level `routers/codeintel.search_payload` backs both the HTTP route and the tool.
- **⚠️ Needs you:** nothing — opt-in (the MCP route-tools kill-switch is off by default) and read-only.
- **Verified (automated):** `tests/test_codeintel_mcp_tool.py` 2 passed (the spec is an allow-listed GET/user
  read tool; the tool reflects its schema and dispatches, filtering unknown args) + the existing
  `test_mcp_route_tools.py` drift-guard (now covering the 4th handler) and `test_route_tools_auth_parity.py`
  still green; ruff + bandit clean; no HTTP route change; STATUS at 3,186 tests.

### 0.31 — Code Intelligence: read-only AST symbol index over the source
- **What:** a new `agents/core/codeintel/` indexing backend — it parses the project's own Python with the
  stdlib `ast` and builds a searchable map of **symbols** (module functions / classes / methods) with their
  kind, relative path, line number, and one-line doc. `GET /api/codeintel/search?q=&kind=` finds where
  something is defined; `GET /api/codeintel/stats` reports the roll-ups; `POST /api/codeintel/reindex`
  (admin) rebuilds the cache. On HEAD it indexes **772 files / ~7,830 symbols / 0 errors**.
- **⚠️ Needs you — nothing, but know the scope:** it returns **structure, not contents** — symbol names,
  kinds, file paths, line numbers, and the first docstring line — never file bodies. It indexes the hub's
  own source (already on GitHub), not your data, and the search/stats routes are user-guarded (reindex is
  admin). Try `GET /api/codeintel/search?q=run_heartbeat` and you should get its definition site.
- **Verified (automated):** `tests/test_codeintel.py` 6 passed (extracts functions/classes/methods with the
  right kinds; doc is only the first non-empty line; `__pycache__` skipped; a syntax-error file is recorded
  under `errors` not fatal; substring + kind-filter search; exact-name-first ranking + limit) and a live
  `project_index()` over the real repo builds with 0 errors; ruff + bandit clean; parity reseeded for the 3
  new routes; STATUS at 3,184 tests / 351 routes.

### 0.55 — Design Partner Kit: diagnostic "issue bundle" (non-sensitive, admin-only)
- **What:** `GET /api/support/bundle` assembles one snapshot a design partner can attach to a support
  request — app version + posture (hardened flags + active system profile) + capability-readiness roll-ups
  + per-plugin egress tallies + recent audit **event counts** & hash-chain integrity + route count — so an
  issue is triagable without a screen-share or a risky data dump. Pairs with the H23.21 feedback/NPS widget
  to round out the kit.
- **⚠️ Needs you — confirm it's safe to hand to a partner (it's designed to be):** safety is by
  **allow-list, not redaction** — the bundle only ever includes the specific aggregates above, never raw
  config, secrets, tokens, message content, audit *previews*, or PII. The audit section is **counts by
  event type only** (e.g. `{"scan": 12, "kernel_grant": 3}`), never the events themselves. A test asserts no
  `token`/`secret`/`password`/`api_key`/`authorization`/`private_key` substring appears anywhere in the
  output. Still worth one real eyeball of `GET /api/support/bundle` on your machine to confirm you're
  comfortable sharing it.
- **Verified (automated):** `tests/test_support_bundle.py` 6 passed (all sections present + JSON-serializable;
  meta carries version + stamp; posture reflects default-off hardened + balanced profile; audit counts-by-
  type from a fake orch with no content leak; a failing source degrades to `{"error":"unavailable"}` instead
  of crashing; and the no-sensitive-keys scan); ruff + bandit clean; parity reseeded for the 1 new admin
  route; STATUS at 3,178 tests / 348 routes.

### 0.62 — System Profiles (usage-mode posture presets; default 'balanced' = no change)
- **What:** named usage modes — **balanced** (default) / **gaming** / **ai** / **multimedia** / **admin** —
  like power plans for the assistant, selected with `JARVIS_SYSTEM_PROFILE` (same env-driven-posture pattern
  as `JARVIS_HARDENED`). Each declares posture knobs (`background_autonomy`, `heavy_features`,
  `max_parallel_agents`, `model_tier`); read-only at `GET /api/system/profiles`. The **first live consumer**
  is wired: a profile with `background_autonomy:false` (gaming / multimedia) **pauses proactive agent
  heartbeats** to free local resources.
- **⚠️ Needs you — try it if you like, but nothing changes by default:** with the env unset the active
  profile is **balanced**, which keeps `background_autonomy:true`, so heartbeats run exactly as before. To
  see it bite: run with `JARVIS_SYSTEM_PROFILE=gaming` and confirm proactive heartbeats stop (and
  `GET /api/system/profiles` shows `active: "gaming"`). Worth a glance to confirm the modes match how you'd
  want the assistant to back off during games/media work. *(Config noted in `docs/OWNER_TASKS.md`.)*
- **Verified (automated):** `tests/test_system_profiles.py` 9 passed (default balanced + autonomy on;
  unknown → fallback; each mode's autonomy knob; `active_posture()` returns a copy; list shape; and the
  **`run_heartbeat` consumer** — runs under balanced, skipped under gaming); ruff + bandit clean; parity
  reseeded for the 1 new user-guarded route; STATUS at 3,172 tests / 347 routes.

### 0.58 — Pack Manager: uninstall an installed skill (safe remove + optional purge)
- **What:** the skill marketplace could install but had no **uninstall** — new `uninstall_skill(name,
  purge=)` + `remove_from_registry(name)` on `skills/marketplace.py`, exposed at
  `POST /api/skills/marketplace/uninstall` (admin). It deletes the installed skill directory and forgets it
  in the live loader; with `purge:true` it also drops the marketplace registry row (full unpublish).
- **⚠️ Needs you — sanity-check the safety + the recovery path:** removal is path-guarded (the target must
  resolve strictly inside `skills/`; a name with `/`, `\`, `..`, or a NUL is refused with a 400), so it
  can't be steered into deleting anything outside the skills dir. By default the published **package is
  retained**, so a `POST /api/skills/marketplace/install` restores the skill — that's the intended
  "undo". True multi-version **rollback** is deferred (the registry keeps one version per name today;
  history needs a small schema change — noted in BACKLOG).
- **Verified (automated):** `tests/test_marketplace_uninstall.py` 12 passed (removes the dir; missing →
  False; refuses `../evil`/`a/b`/`..`/`.`/`x\y`/NUL/empty; refuses the skills dir itself; `purge` drops the
  registry row while default retains it for reinstall) + the existing marketplace/skills suite (106) still
  green; ruff + bandit clean; route/openapi/auth parity reseeded for the 1 new admin route; STATUS at 3,163
  tests / 346 routes.

### 0.44 — per-channel outbound send rate limits (opt-in, default-off)
- **What:** a new `channels/send_rate_limit.py` — a sliding-window limiter that bounds how *much* the
  external webhook channels (WhatsApp / Signal / Matrix / Teams / Google Chat) can broadcast, wired at
  `WebhookChannel.send()`. It's the third leg of the comms-safety stool: CDX-11 governs *who* may use a
  channel, the H23.16 egress monitor *observes* the volume, and this *bounds* it. **Off by default**
  (unlimited) — set `JARVIS_CHANNEL_SEND_RATE=<per-min>` globally and/or
  `JARVIS_CHANNEL_SEND_RATES="whatsapp:10,teams:30"` per channel to turn it on. Over the cap → the send is
  dropped (returns False) and logged.
- **⚠️ Needs you — only the policy, and only if you want it on.** Default changes nothing. I made one
  deliberate scoping call you should be aware of: the limiter covers the **external broadcast channels
  only**, NOT the interactive reply path (telegram / web / voice). That's intentional — rate-limiting a
  reply could silently swallow a legitimate answer to you, which is worse than the flood it would prevent.
  If you ever *do* want the reply path bounded too, that's a different design we should talk through.
  (Config noted in `docs/OWNER_TASKS.md`.)
- **Verified (automated):** `tests/test_channel_send_rate_limit.py` 10 passed (default-unlimited; global +
  per-channel cap parsing with junk entries ignored; the sliding window expiring old hits; independent
  per-channel budgets; and the `WhatsAppChannel.send` integration where the over-cap send never reaches the
  transport) + the existing webhook-channel suite still green; ruff + bandit clean; no new routes; STATUS at
  3,151 tests.

### 0.43 — Learning Coach Pack (SM-2 spaced repetition + curriculum, stateless)
- **What:** a new offline study-coach pack (`agents/core/coach/`, separate from the agent-promotion
  `learning/scheduler.py`). Three stateless capabilities — **SM-2 spaced repetition**
  (`POST /api/coach/review` → a card's next interval/ease/due-day), a **review-session builder**
  (`POST /api/coach/session` → today's due cards + capped new cards, with honest deferred-counts), and a
  **curriculum planner** (`POST /api/coach/curriculum` → topics ordered by prerequisites, split into
  sessions). The caller holds card state; the server only computes the schedule.
- **⚠️ Needs you — nothing, but worth a sanity-check on the algorithm:** it's the textbook SM-2 (Anki's
  lineage), so `review` on a fresh card with quality 5 → interval **1 day**, again → **6 days**, then it
  scales by the ease factor; a poor grade (<3) **resets** repetitions and floors ease at 1.3. The planner
  surfaces prerequisite **cycles** and **unknown prereqs** rather than silently dropping topics. It plans
  and schedules only — it never invents lesson content and never persists.
- **Verified (automated):** `tests/test_coach_pack.py` 8 passed (the 1-day/6-day/ease-scaled SM-2 steps,
  lapse-reset + ease floor, input-not-mutated, due/new split with honest counts, never-reviewed-is-new,
  prereq ordering, and honest cycle/unknown reporting); ruff + bandit clean; parity reseeded for the 3 new
  user-guarded routes; STATUS at 3,143 tests / 345 routes.

### 0.42 — Security Skills Pack (curated ATT&CK / D3FEND / NIST CSF knowledge, read-only)
- **What:** a new offline knowledge pack (`agents/core/security_skills/`, separate from the `security/`
  infra) over **public** taxonomies — MITRE ATT&CK (all 14 tactics + a curated subset of techniques with
  real IDs), MITRE D3FEND (countermeasures mapped to the techniques they counter), and NIST CSF 2.0 (the 6
  functions). It maps a free-text behavior to candidate ATT&CK techniques (an honest keyword heuristic that
  returns the matched evidence — not a black-box classifier) and assembles a defensive playbook
  (countermeasures + CSF coverage, with honest gaps + unknown-id reporting). Read-only at
  `/api/security-skills/{frameworks,tactics,techniques,technique/{tid},map,playbook}`.
- **⚠️ Needs you — eyeball the honesty + accuracy:** this is the kind of pack where *honesty* is the whole
  point, so spot-check a couple of things: (1) `GET /api/security-skills/technique/T1486` should show the
  ransomware technique mapped to **File Backup & Restore** → CSF **Recover**; (2) `POST
  /api/security-skills/map` with `{"behavior":"attacker used powershell then exfiltrated data"}` should
  surface **T1059** + **T1041** *with the matched keywords as evidence*; (3) every payload carries
  `curated:true`, a `DISCLAIMER`, and `SOURCES` — confirm it reads as "curated educational subset", never
  "complete control set". It never fabricates an ID and never acts (pure knowledge).
- **Verified (automated):** `tests/test_security_skills_pack.py` 8 passed (tactics complete + provenance,
  technique enrichment, the keyword heuristic + its evidence, honest playbook gaps/unknowns, framework
  overview, no fabricated D3FEND buckets); ruff + bandit clean; route/openapi/hud-v2 parity reseeded for
  the 6 new user-guarded routes; STATUS at 3,135 tests / 342 routes.

### 0.36 — the agent-native route manifest is now pinned to route_auth.json (no more drift)
- **What:** the MCP route tools (`mcp/route_tools.py`) expose a small curated set of HTTP routes to the
  model — 3 read (`/status`, `/api/memory/search`, `/dashboard`) and 1 double-gated write
  (`/api/memory/remember`). That allow-list declared nothing about each route's auth, so it could drift
  from the route's real guard or (worse) silently expose an over-privileged route as an agent **read**
  tool. Each spec now declares a `guard`, and a new parity gate pins it to `route_auth.json` (the SEC-2
  source of truth): CI fails if the manifest drifts, names a non-existent path, exposes an **admin**
  route as a read tool, or lists an **open** (unauthenticated) **write** tool.
- **⚠️ Needs you:** nothing — pure CI hardening, no runtime/behavior change. Noted only so you know that
  if you ever add a route to the agent allow-list, you'll also declare its `guard` and the gate will
  hold it to the real auth snapshot.
- **Verified (automated):** `tests/test_route_tools_auth_parity.py` 3 passed (read tools match + are
  not admin; write tools match + are authenticated; read/write allow-lists are disjoint) + the existing
  `test_mcp_route_tools.py` suite still green; ruff + bandit clean; no new routes; STATUS at 3,127 tests.

### CDX-7 follow-up — the agentic-RAG *tool* path now redacts injected memory too
- **What:** CDX-7 fenced retrieved memory at the *prompt-string* sites, but the LLM-callable
  `search_memory` tool (`MemorySearchTool.search()`, behind `POST /api/memory/search-tool`) returns
  hit-*dicts* straight to the model — a path it explicitly deferred because `wrap_memory` is
  string-shaped. Now each hit is run through the injection scanner; a flagged hit is **redacted**
  (its text → `[REDACTED: injection-flagged memory]`, tagged `injection_flagged`, with `flags`), while
  its score/provenance are kept so ranking + explainability still work. Clean hits are byte-identical.
  On by default; a `scan=False` constructor opt-out exists for callers that sanitized upstream.
- **⚠️ Needs you:** nothing — this is a transparent safety scan with no behavior change for clean
  memory. Only a stored entry that actually looks like an injection (e.g. "ignore previous
  instructions…") is masked in the tool result. Mentioned only so you know why such an entry would
  show `[REDACTED…]` if you ever inspect `/api/memory/search-tool` output.
- **Verified (automated):** `tests/test_cdx7_rag_tool_scan.py` 6 passed (clean passthrough, redaction +
  metadata preservation, the `name`-field variant, a mixed batch redacting only the flagged hit, the
  `scan=False` opt-out, and the agentic loop inheriting the scan) + the 8 existing H8.3b agentic-RAG
  tests still green; ruff + bandit clean; no route change; STATUS at 3,124 tests.
- **Still deferred (the genuinely hard one — flagging for your call):** carrying taint *through* a
  memory-derived **action** to the Action Kernel (so a GRANT escalates to QUEUE) is full data-flow
  propagation — `taint.py`'s own docstring documents it as deferred, and the naive hook broke with a
  NameError last time. That one wants a design decision, not a blind attempt.

### CDX-12 — the "Design-Partner / Hardened" profile (one switch, opt-in, default-off)
- **What:** a single `JARVIS_HARDENED=1` preset that tightens four security toggles at once for a
  design-partner / multi-tenant deployment, plus it turns on CDX-11 plugin least-privilege. The four:
  **(1)** guardrails default `WARN → REDACT`; **(2)** the audit log **must** be HMAC-keyed
  (`JARVIS_AUDIT_KEY`) or the server **refuses to start**; **(3)** strict egress is **forced** (the
  `JARVIS_STRICT_EGRESS=0` downgrade is ignored); **(4)** mutating MCP route tools are **forced off**
  (`JARVIS_MCP_MUTATING_TOOLS` can't re-open writes). New `agents/core/security/hardened.py` owns the
  logic; four one-line wirings consult it; nothing else changed.
- **⚠️ Needs you — only when you decide to run hardened.** Default is **OFF**: with the env unset, every
  toggle is exactly its pre-CDX-12 value (the whole suite confirms). To enable: set `JARVIS_HARDENED=1`
  **and** `JARVIS_AUDIT_KEY=<off-box secret>` (without the key, startup fails closed by design — a
  hardened box whose audit chain can't be HMAC-keyed is mis-configured, not merely weaker). Turning it
  on also makes the 12 external-write plugins deny-by-default (CDX-11) — so pair it with
  `JARVIS_PLUGIN_GRANTS` (see the CDX-11 note). This is a **posture decision**, documented in
  `docs/OWNER_TASKS.md`; the code picks no profile for you.
- **How to eyeball it:** `GET /api/security/posture` now carries a `hardened` block reporting all toggles
  (`enabled`, `guardrails_mode_default`, `audit_key_required`/`audit_key_present`, `strict_egress_forced`,
  `mutating_mcp_blocked`, `plugin_least_privilege`). Flip the env on a scratch run and confirm it reads true.
- **Verified (automated):** `tests/test_cdx12_hardened_profile.py` 11 passed — each toggle off-by-default,
  each flips under the preset, fail-closed without the audit key (incl. the `serve.assert_hardened_posture`
  startup guard), the posture-snapshot shape, the strict-egress + mutating-MCP overrides actually bite, and
  the CDX-11 least-privilege cross-wire. ruff + bandit clean; no new routes (parity green); STATUS at 3,118 tests.

### CDX-11 — least-privilege plugins (opt-in hardened profile; default-off, nothing changes yet)
- **What:** 12 plugins that **transmit to a third party** ship `agents_served=["all"]` — the 11
  external-write surfaces (`social_x`, `writeback_{notion,github,google_calendar}`,
  `call_{twilio,telnyx}`, `channel_{whatsapp,google_chat,teams,signal,matrix}`) plus the `telegram`
  comms bus. With `"all"`, *any* agent persona — including one steered by an injected prompt — can
  reach those writes. New least-privilege overlay on the permission gate: under hardening the `"all"`
  wildcard is **no longer honored for TRANSMITTED plugins**; each admits only an explicitly-served
  agent or an **owner-declared grant**. Read/LAN/local plugins (weather, news, websearch, homebridge…)
  keep their wildcard; already-scoped plugins (e.g. `cloud-llm`) are untouched.
- **⚠️ Needs you — but only if you turn it on.** This ships **OFF by default**: with no env set,
  behavior is byte-identical to before (every existing test confirms this). To harden, set
  `JARVIS_PLUGIN_LEAST_PRIVILEGE=1` (or the `JARVIS_HARDENED` preset, which CDX-12 will flip), then
  declare grants via `JARVIS_PLUGIN_GRANTS="social_x:veronica,writeback_github:stark,…"`. The code
  **deliberately does not guess** which agent should own which write surface — that capability matrix
  is yours to set (also noted in `docs/OWNER_TASKS.md`). Until you do, hardened mode is fail-closed:
  the external-write plugins are denied for everyone, which is the correct hardened posture.
- **How to eyeball it:** `GET /plugins` now reports `least_privilege` (top-level) and, per plugin,
  `wildcard_restricted` (is its `"all"` currently withheld?) + `grants` (who you've allowed). Flip the
  env on a scratch run and confirm the 12 transmit plugins show `wildcard_restricted:true` while reads
  stay false.
- **Verified (automated):** `tests/test_cdx11_least_privilege_plugins.py` 11 passed — default-off
  serves everyone, hardened blocks the wildcard external-writes, a grant re-admits exactly one
  plugin+agent, reads/LAN/explicit-scoped plugins are unaffected, the full 12-plugin target set is
  restricted, and both env switches + the grant parser wire through. ruff + bandit clean; no new
  routes (parity green); STATUS at 3,107 tests.

### CDX-8 — auto-generated skills are quarantined (owner-approve before they can run)
- **What:** an agent that emitted `[learn: task | steps | cmd]` minted a brand-new skill **from untrusted LLM
  output**, and the loader then **self-signed it and `exec`'d its Python module in-process on the spot** —
  making a model-authored skill strictly *more* trusted than one you downloaded from the marketplace (which at
  least passes the signature/moderation gate). That's a clean injection→code path. Now it's **fail-closed**:
  the task/steps/command are scanned with the injection scanner **before anything touches disk** (flagged →
  refused, nothing written); a clean skill is minted **`PENDING_REVIEW`** — registered so you can *see* it, but
  its module is **never exec'd** (`sandboxed`, regardless of the signed-skills env); provenance (which agent,
  what task, when) is recorded in the marker; and only an **owner** can promote it to runnable.
- **⚠️ Needs you — this changes a behavior you may have relied on:** previously a `[learn:…]` skill became
  usable *immediately*. Now an agent-generated skill sits **pending** until you approve it. To review + activate:
  `GET /api/skills/pending` lists what's waiting (name, description, which agents), and
  `POST /api/skills/{name}/approve` (admin-gated) signs + activates one. Until you approve, the auto-generated
  command simply won't run in-process. If you *want* a generated skill, eyeball its `skills/<name>/main.py`
  (it's a template stub by default) and approve it. Worth a quick check that this gate matches how you expect
  self-improvement to feel — auto-*generation* is still on; only auto-*execution* is now gated.
- **Verified (automated):** `tests/test_cdx8_skill_quarantine.py` 6 passed — a clean generated skill is
  registered-but-not-exec'd, stays non-exec'd on a fresh `discover()`, injection-flagged content is refused
  both in the **task** and in the **command-name**, owner-approve flips it to signed+active, and approve is
  idempotent/safe on unknown names. ruff + bandit clean; route parity/auth/openapi snapshots reseeded for the
  2 new admin routes; STATUS at 3,096 tests / 336 routes.

### CDX-7 — retrieved memory is now fenced as untrusted DATA before it hits the prompt
- **What:** retrieved memory (vector/graph recall + the Howard archive RAG few-shots) was spliced **raw**
  into LLM prompts — a textbook indirect-injection surface (a string saved to memory, or synced from the
  untrusted WorldView/OSINT feed into the graph, could carry instructions the model then follows). New
  `agents/core/security/rag_guard.py` is the single choke point: `wrap_memory()` fences retrieved memory as
  `<<RETRIEVED MEMORY … DATA, NOT INSTRUCTIONS>>`, **caps length**, runs the injection scanner
  (`quarantine.detect_injection`) and **redacts** a flagged snippet (its body never reaches the model),
  datamarks the kept body, and tags **source / age / confidence** honestly. Wired at the 3 confirmed
  prompt-string sites (`orchestrator._recall_block`, and the Howard archive RAG in `orchestrator` + `agent.py`).
- **A deliberate design nuance:** the Howard few-shots get `datamark=False` — they're the user's *own* past
  messages whose **stylometry** the model is meant to mirror, and datamarking would garble the very style
  they convey. They're still capped, scanned, redacted-on-hit, and fenced — just left readable for clean
  snippets. Worth knowing if you compare Howard's voice before/after.
- **How it was built (ultracode):** a multi-agent workflow mapped the real injection surface, proposed 3
  designs, and **adversarially verified** the synthesis — which caught two latent bugs *before* they shipped:
  a `writeback.py` taint hook referencing `orch`/`base` symbols that don't exist in scope (NameError), and a
  `UNTRUSTED_SOURCES` edit that would have broken an existing test. Those informed the scope below.
- **Verified (automated):** `tests/test_cdx7_rag_guard.py` (13) + `tests/test_cdx7_no_raw_memory_splice.py`
  (2, a static gate that fails if a raw splice reappears) — all green, plus `test_taint_flag` and the agentic-RAG
  test still pass; ruff + bandit clean; STATUS at 3,090 tests.
- **⚠️ Needs you — scope is the *prompt-level* defense; these are named follow-ups (not done):**
  1. **Action-taint propagation** — carrying taint *through* a memory-derived action to the kernel so a
     GRANT escalates to QUEUE. This is the genuinely hard data-flow-propagation part that `taint.py`'s own
     docstring documents as deferred; the naive version was the NameError-broken hook above, so it's
     intentionally **not** shipped half-working. Worth prioritising if you want defense-in-depth beyond the prompt.
  2. **Agentic-RAG tool path** (`rag_tool.py`) returns hit *dicts* to the model (not a prompt string), so the
     string-based `wrap_memory` doesn't fit as-is — needs a per-hit scan/redact variant.
  3. Two more recall routes (`memory_kg.recall_memory`, HTTP `memory_search`) — the latter returns UI JSON,
     not a prompt, so lower priority.

### CDX-10 — `_sys_info()` is now honest (no fabricated host/CPU/GPU on the readiness screen)
- **What:** `/status` (the trust/readiness screen) used to show plausible-but-**fabricated** hardware when
  probes failed — `host="BONOBO-WS"`, `gpu="RTX 5090 · 24GB"`, a hardcoded "Intel Core Ultra 9" CPU brand,
  and a `model`/`backend` it never actually probed. `_sys_info()` now probes every value (real hostname,
  real CPU model via `platform.processor()`→`/proc/cpuinfo`→thread count, real RAM via psutil, real GPU
  name+VRAM via `nvidia-smi` guarded by `shutil.which`) and degrades to **`unknown` / `none` / `0`** on
  failure — never a guessed card or model. Same "never fake" ethos as the packs' `no_quote` / `generated:false`.
- **⚠️ Needs you (cosmetic, expected):** on your real hardware the screen will now show your *actual*
  host/CPU/GPU; on a box without an NVIDIA GPU it shows `gpu: none` (not a fake card), and `model`/`backend`
  read `unknown` here (the live model is shown by the LLM-state panels, not this hardware probe). Glance at
  the readiness screen once to confirm the real values populate as you'd expect.
- **Verified (automated):** `tests/test_sys_info_honest.py` 5 passed (shape stable; the old fabrications are
  gone; host is the real hostname or `unknown`; GPU is honest when absent); ruff + bandit clean (bandit
  baseline regenerated 125→119 as the `contextlib.suppress` refactor removed stale `try/except/pass` entries).

### P4 — Creative / Publishing pack: a planner with provenance + a VERIFIED publish-safety rail (Track P)
- **What:** `agents/core/creative/pipeline.py` — a pure/deterministic creative-pipeline **planner** over a
  brief (no media-gen): `plan_pipeline` lays out the ordered stages (script → image_prompts → render →
  assemble → export), each carrying **provenance** (its inputs + the null generator it *would* call) and
  `generated: false` — nothing is ever faked as a finished asset. `build_export_packs` produces per-platform
  delivery **specs** for **YouTube / Instagram / README** (aspect/size/format/caption-kind); an unmodeled
  platform is dropped, never invented. Served at `POST /api/creative/plan` + `POST /api/creative/export-packs`
  (`user_guard`'d, offline). `tests/test_creative_pipeline.py` (+7); parity gates reseeded.
- **The publish-safety contract is VERIFIED with real primitives** (a hermetic `reality_harness` case
  promoting `plugin:social_x`): the pipeline drafts/plans freely (`creative.draft` → **GRANT**), but the
  terminal **release** — publishing a finished campaign to the world (an irreversible side-effect) — is held
  by the real `kernel.authorize` (`IRREVERSIBLE_OR_MONEY` → **QUEUE**). So **nothing is auto-published on
  your behalf**: you approve every release.
- **Verified (automated):** `tests/test_creative_pipeline.py` 7 passed (plan stages + provenance, export
  specs for the 3 platforms, honest empty-brief + dropped-unknown-target, the release→QUEUE governance
  proof, and the reality-case promotion); ruff + bandit clean; all parity gates green (334 routes); STATUS
  at 3,070 tests.
- **⚠️ NEEDS YOU (owner-gated, live):** the engine *plans* — it doesn't *render or publish*. Real media
  generation (image/video models) and the platform upload APIs need keys + network and are owner-gated
  wiring (`docs/OWNER_TASKS.md`). Worth a manual smoke once wired: POST a brief to `/api/creative/plan`,
  confirm the stages/export specs read right, and verify a release lands in the approval queue (never
  auto-published).

### P3 — Market Intel + Finance pack: offline intel + a VERIFIED money-safety rail (Track P)
- **What:** `agents/core/market/analyze.py` — a pure/deterministic market-intel engine over *provided*
  quotes/positions (no live fetch): `evaluate_watchlist` (band breaches → alerts; an absent quote is an
  honest `no_quote`, never a fabricated price), `portfolio_snapshot` (net worth + per-position weight +
  by-kind allocation; drops unpriced rows rather than guessing), and a demoable `daily_brief`. **Every alert
  and brief carries a mandatory not-advice `DISCLAIMER`.** Served at `POST /api/market/watchlist` +
  `POST /api/market/brief` (`user_guard`'d, offline). `tests/test_market_intel.py` (+10); route
  parity/auth/openapi/hud-v2 reseeded.
- **The money-safety contract is VERIFIED with real primitives** (a hermetic `reality_harness` case promoting
  `plugin:balance`): a market-triggered **money action** (`trade.buy` / `transfer.funds`) is held by the real
  `kernel.authorize` — classified `IRREVERSIBLE_OR_MONEY` → **QUEUE** (approval) — while read-only
  `market.monitor` is **GRANT**ed. So **money never auto-moves**: the pack can watch the market freely but
  can't act on your behalf without approval.
- **Verified (automated):** `tests/test_market_intel.py` 10 passed (watchlist/portfolio/brief + disclaimer
  enforcement + the money→QUEUE governance proof + the reality-case promotion); ruff + bandit clean; all
  route/auth/openapi/hud-v2 parity gates green (332 routes); STATUS at 3,063 tests.
- **⚠️ NEEDS YOU (owner-gated, live):** the engine *analyses* provided data — it doesn't *fetch*. Real quotes
  (a broker/market-data API) and real balances (the `balance` plugin against ING/Libra) need keys + network
  and are owner-gated wiring (`docs/OWNER_TASKS.md`). Worth a manual smoke once wired: POST a real watchlist +
  positions to `/api/market/brief` and confirm the alerts/snapshot + disclaimer read right, and that a
  money action proposed off an alert lands in the approval queue (never auto-applied).

### P2 — OSINT pack: governed correlation + a VERIFIED ingestion-trust rail (Track P)
- **What:** the first slice of the **P2 OSINT Investigator pack** — `agents/core/osint/correlate.py`, a
  pure/deterministic correlation engine over *provided* evidence (WorldView/Argus, web, RSS, manual). It
  groups evidence by indicator into **findings** with a provenance chain + a transparent corroboration-based
  confidence, **taints untrusted-source evidence at the ingestion boundary** (`security.taint`), and
  propagates that taint onto any write-back payload (`writeback_payload`). Served at
  `POST /api/osint/correlate` + `POST /api/osint/brief` (`user_guard`'d). `tests/test_osint_correlate.py`
  (+11); route parity/auth/openapi snapshots reseeded.
- **The governance contract is VERIFIED with real primitives** (a hermetic `reality_harness` case promoting
  `plugin:worldview`): a low-risk OSINT write-back the autonomy policy *would* GRANT is escalated
  **GRANT→QUEUE** by the real `kernel.authorize` when it carries untrusted-source taint — while the same
  write from a trusted operator source is GRANTed. So **intel from an untrusted source can never
  auto-execute** — it routes through approval. This closes P2's "ingestion trust-boundary enforced" AC.
- **Verified (automated):** `tests/test_osint_correlate.py` 11 passed (engine + taint propagation + the
  GRANT→QUEUE governance proof + the reality-case promotion); ruff + bandit clean; route/auth/openapi parity
  reseeded (330 routes); reality-harness + status-sync suites green.
- **⚠️ NEEDS YOU (owner-gated, live):** the engine *correlates* — it doesn't *collect*. Real OSINT
  collection (SpiderFoot modules, the WorldView REST on `:4000`, news/RSS feeds) needs keys + network and is
  owner-gated wiring (`docs/OWNER_TASKS.md`). Worth a manual smoke once wired: POST a batch of real evidence
  to `/api/osint/correlate` and confirm the drawer + taint flags look right, and that a tainted write-back
  shows up in the approval queue (not auto-applied).

### HUD — type `gap.tsx` → CDX-9 component sweep COMPLETE 🟢 (CDX-9 typing pass)
- **What:** removed `@ts-nocheck` from `gap.tsx` (the big P4c "console" overlay — sessions, OAuth, settings
  DB, prompt versions, and ~20 other admin/data panels). 25 errors, all type-only:
  - the shared `Card`/`Tag` panel primitives required `sub`/`onReload`/`c` while most callers omit them
    (all have runtime guards/fallbacks) → marked optional.
  - `act()`'s 3rd callback arg is optional (`then || (()=>{})`) → `then?`.
  - the `SECTIONS` panel-registry tuples were widened to `string | Component[]` unions → typed
    `Array<[string, Array<() => any>]>`.
  - `dirty`/settings state typed `Record<string, any>`, and the `useApi`/`apiGet`/`apiPut` `unknown`
    responses narrowed `: any` at their `.then`/`.map` boundaries (live.ts-ingestion style).
- **🟢 This completes the CDX-9 component sweep.** The **entire HUD source tree is now `@ts-nocheck`-free**
  (22 modules typed across #379–#396; the only directives left are on `src/test/*` fixtures). `tsc --noEmit`
  is clean, and the production bundle was **byte-identical at every step except one** — #389, the single
  intentional drift-fix (the modes2 dropped-style, flagged below).
- **Verified (automated):** `tsc --noEmit` clean; frontend **vitest 73 passed**; `agents/web/v2` bundle
  **byte-identical**. No backend/route change.
- **⚠️ Needs you — the consolidated CDX-9 review list** (each already detailed in its own entry below):
  1. **modes2 header spacing** (#389) — the one *visual* change; eyeball the Autonomy/Observe/Interop panels.
  2. **app.tsx tabs-IA is dead code** — `ia` pinned to `'rail'`; decide wire-back-or-delete later.
  3. Everything else is compile-time-only and behaviour-identical — no action needed, but the sweep
     surfaced real latent issues now fixed: a dead `_wrap` ref (network), the `Icon`/`SubH`/`Meter`
     optional-prop contracts, and the plugin/payment seed-vs-live `id` drift.

### HUD — type `shell.tsx` (CDX-9 typing pass)
- **What:** removed `@ts-nocheck` from `shell.tsx` (topbar, rail/tabs nav, ticker, right context column,
  ambient, palette). 9 errors, two patterns, both type-only:
  - the `MODES` nav array reads `m.locked` — a **forward-looking "soon"-disable flag** (the rail/tabs gray
    out and block locked modes) that **no MODES item currently sets**. Annotated the array element type with
    optional `locked?` (plus the other optional `id/icon/tkey/live/sep`) so the defensive read is honest.
  - the shared `Meter` primitive required `unit`, but 3 callers (the topbar gauges) omit it — and `Meter`
    renders `{unit||'%'}`, so it's optional. Marked it optional at `Meter`'s def in `primitives.tsx` (one
    cross-file fix, same shape as the `Icon` fix in #384).
  1 non-test source module remains on `@ts-nocheck` (the last one: `gap.tsx`).
- **Verified (automated):** `tsc --noEmit` clean; frontend **vitest 73 passed**; `agents/web/v2` bundle
  **byte-identical**. No backend/route change.
- **⚠️ Needs you:** nothing — compile-time only, behaviour-identical.

### HUD — type `app.tsx` (CDX-9 typing pass)
- **What:** removed `@ts-nocheck` from `app.tsx` (the root composition — state, the streaming-turn loop,
  the layout). The most complex slice; 11 errors → 5 root type-only fixes (bundle byte-identical):
  - `messages` state was inferred as a narrow 2-shape literal union, so the optimistic-update callbacks
    didn't type-match → `useState<any[]>` (clears 3 cascading `SetStateAction` errors at the source).
  - the `seq` staged-timer array was widened from `[number, fn]` tuples to a union, breaking `setTimeout` →
    annotated `Array<[number, () => void]>`.
  - `mark()`'s trailing `j, jstate` are optional (the body guards `j !== undefined`) → `j?, jstate?`.
  - `cog` from `apiGet('/api/cognition')` → `: any` boundary.
  - **a small dead-code find:** `const ia = 'rail'` is hardcoded, so the `ia === 'tabs'` (Tabs-layout)
    branch is unreachable. Typed it `'rail' as 'rail' | 'tabs'` so the comparison is valid **without
    changing behaviour** — Tabs stays unrendered exactly as today.
  2 non-test source modules remain on `@ts-nocheck` (the last two: `shell`/`gap`).
- **Verified (automated):** `tsc --noEmit` clean; frontend **vitest 73 passed**; `agents/web/v2` bundle
  **byte-identical**. No backend/route change.
- **⚠️ Needs you (informational, not a bug):** the **tabs information-architecture** is dead code — `ia`
  is pinned to `'rail'`, so the alternative `<Tabs>` top-nav layout (imported from `shell.tsx`) never
  renders. It was evidently an A/B layout that got fixed to the rail. No action needed for the typing pass;
  flagging in case you want to either wire `ia` to a real preference (and offer tabs again) or delete the
  dead `<Tabs>` path in a future cleanup.

### HUD — type `modes.tsx` (CDX-9 typing pass)
- **What:** removed `@ts-nocheck` from `modes.tsx` (Agents / Trust / Memory modes). 9 errors, all type-only:
  - three **API-response boundaries** — `decidePayment`, `setKillSwitch`, `memorySearch` all return
    `Promise<unknown>`; annotated their `.then`/`.map` callback params `: any` (the same arbitrary-backend-JSON
    boundary `live.ts` uses).
  - the **PAYMENTS-seed `.id` drift** (same shape as the plugin-registry case in #392): the payments ledger
    seeds from `V2.PAYMENTS` with no `id`, but `live.ts` swaps in real broker payments *with* `id`, and the
    approve/reject/settle lifecycle buttons render only when it's present (`{p.id && p.state==='pending' && …}`).
    Typed the map element with optional `id?` so the seed/live duality is honest.
  3 non-test source modules remain on `@ts-nocheck` (the last three: `app`/`shell`/`gap`).
- **Verified (automated):** `tsc --noEmit` clean; frontend **vitest 73 passed**; `agents/web/v2` bundle
  **byte-identical**. No backend/route change.
- **⚠️ Needs you:** nothing — compile-time only, behaviour-identical.

### HUD — type `modes3.tsx` + relax the `InputBar` contract (CDX-9 typing pass)
- **What:** removed `@ts-nocheck` from `modes3.tsx` (Chat / Comms / Admin modes) — the richest mix in the
  sweep so far, 8 errors across 4 distinct patterns, **all type-only** (bundle byte-identical):
  1. `SubH3` — the recurring local-header optional-`style` fix.
  2. **`InputBar` contract** — modes3's distraction-free `ChatMode` renders `<InputBar>` *without*
     `voice/cfg/onCfg/micMuted`, which `InputBar` already guards (`voice && …`) but were inferred as
     required. Relaxed them to optional at `InputBar`'s definition in **`cockpit.tsx`** (one cross-file
     follow-up that unblocks any minimal InputBar caller).
  3. **plugin-registry `id` drift** — the Admin plugin list seeds from `V2.ADMIN.plugins` (no `id`), but
     `live.ts` swaps in the real registry *with* `id`, and the toggle handler keys off it
     (`if(!p.id) return` → demo rows flip locally; real rows POST `/plugins/{id}/toggle`). Typed the state
     with optional `id?` so the seed/live duality is honest.
  4. `togglePlugin`'s `Promise<unknown>` response → `: any` at the read boundary (codebase-consistent).
  4 non-test source modules remain on `@ts-nocheck`.
- **Verified (automated):** `tsc --noEmit` clean; frontend **vitest 73 passed**; `agents/web/v2` bundle
  **byte-identical**. No backend/route change.
- **⚠️ Needs you:** nothing — compile-time only, behaviour-identical.

### HUD — type `modes4.tsx` (CDX-9 typing pass)
- **What:** removed `@ts-nocheck` from `modes4.tsx` (the Finance / Health / Knowledge / Family agent-home
  modes). All 8 errors were the same optional-prop fix: the local `SubH4` **already renders `style={style}`
  correctly** (no dropped-style drift, unlike modes2's `SubH`), it was merely inferred as *requiring*
  `style` while 8 callers omit it. One-line `{ children?: any; style?: any }`. Type-only; bundle
  byte-identical. 5 non-test source modules remain on `@ts-nocheck`.
- **Verified (automated):** `tsc --noEmit` clean; frontend **vitest 73 passed**; `agents/web/v2` bundle
  **byte-identical**. No backend/route change.
- **⚠️ Needs you:** nothing — compile-time only, behaviour-identical.

### HUD — type `cockpit.tsx` (CDX-9 typing pass)
- **What:** removed `@ts-nocheck` from `cockpit.tsx` (the conversation + cognition-trace + input column).
  A clean **root-cause** fix: `buildTrace()` built its per-agent routing scores into an untyped `{}`
  accumulator, so `Object.entries(agentScore)` typed every value as `unknown` — which then broke the
  `.sort((a,b)=>b.v-a.v)`, the `s.v>=0.6` / `conf<0.6` comparisons, and the `scored[0].win=true` flag
  (5 errors, all the same origin). Typed the accumulator `Record<string, number>` and widened the
  scored-element type to carry the optional `win`. Type-only; bundle byte-identical. 6 non-test source
  modules remain on `@ts-nocheck`.
- **Verified (automated):** `tsc --noEmit` clean; frontend **vitest 73 passed**; `agents/web/v2` bundle
  **byte-identical**. No backend/route change.
- **⚠️ Needs you:** nothing — compile-time only (the cognition trace is a deterministic client-side
  demo built from the seeded `COGNITION_SCORING`; no behaviour change).

### HUD — type `modes2.tsx` + fix a dropped-style drift ⚠️ FIRST VISUAL CHANGE (CDX-9 typing pass)
- **What:** removed `@ts-nocheck` from `modes2.tsx` (the Autonomy / Build / Observe / Interop modes).
  Stripping it exposed a real **dropped-style bug**: this file's *local* `SubH` was
  `function SubH({ children })` rendering `<div className="sub-h">{children}</div>` — it accepted **no**
  `style` prop, yet **6 secondary section headers** pass `style={{marginTop:16}}` (or `14`):
  OBSERVER LOG, PER-AGENT SCOPE, MODEL ARENA, RESILIENCE, MCP SERVERS, WEBHOOKS. The margin was silently
  discarded. The **sibling `SubH` in `world-intelligence.tsx` renders `style={style}`** and applies the
  identical `marginTop:16` for the identical purpose — so modes2's headers have been missing the app-wide
  spacing the rest of the HUD uses. I made modes2's `SubH` match (`{ children, style }` → `style={style}`).
  Also narrowed `setAutonomyMode(m)`'s `Promise<unknown>` result where `.mode` is read (type-only).
- **⚠️ NEEDS YOU — this is the FIRST slice that changes the rendered bundle.** It adds ~16px top-margin to
  those 6 section headers in the Autonomy/Observe/Interop panels. **Eyeball those panels** to confirm the
  extra spacing looks right (it should — it matches how the same headers already render in the World
  Intelligence panel). If you'd rather keep them tight, it's a one-line revert (drop `style={style}` from
  modes2's `SubH`). Low-risk: the change brings modes2 *into consistency* with the rest of the app, it
  doesn't invent new styling.
- **Verified (automated):** `tsc --noEmit` clean; frontend **vitest 73 passed**; `npm run build` rebuilt the
  bundle (new hash `index-C6ME69L3.js`, deterministic) — committed so the `hud-v2-build` parity guard
  matches. No backend/route change.

### HUD — type `voice.ts` (CDX-9 typing pass)
- **What:** removed `@ts-nocheck` from `frontend/src/voice.ts` (the browser-side hands-free voice loop:
  mic capture → VAD segmentation → `/api/voice/stt` → chat turn → server `/tts` playback with a
  `speechSynthesis` fallback). First file in the sweep with **substantive** type errors rather than the
  optional-prop pattern. Five fixes, **all type-only** (bundle byte-identical):
  1. `useVoice({ … onTurn })` — the `onTurn` callback was destructured but missing from the inferred
     options type; annotated the options shape.
  2. `tok(extra?)` — header helper with an `extra||{}` fallback, called once with no args; marked optional.
  3. `window.webkitAudioContext` — Safari/legacy `AudioContext` fallback; typed cast (not `any`).
  4. `new Blob([frame.audio])` — the TS-5.7 `Uint8Array<ArrayBufferLike>` → `BlobPart` lib quirk; cast.
  5. the `streamTts` `onFrame` callback returned `Promise<unknown>` vs the expected `Promise<void>|void`
     — `streamTts` **awaits** `onFrame` to keep sentence-by-sentence playback **in order**, so I
     cast-preserved the returned promise rather than dropping it (dropping it would desync playback).
  8 non-test source modules remain on `@ts-nocheck`.
- **Verified (automated):** `tsc --noEmit` clean; frontend **vitest 73 passed** (incl. `ttsStream.test`);
  `agents/web/v2` bundle **byte-identical**. No backend/route change.
- **⚠️ Needs you:** the voice loop is **typecheck/build-verified only** — live mic + audio playback need a
  real browser + device a headless CI can't provide (this was already the file's documented stance). A
  one-time hands-free smoke test on real hardware confirms the loop end-to-end; the typing change here is
  purely compile-time and behaviour-identical (playback ordering explicitly preserved — see fix #5).

### HUD — type `world-intelligence.tsx` + `modes_world.tsx` (CDX-9 typing pass)
- **What:** removed `@ts-nocheck` from the WorldView pair — `world-intelligence.tsx` (the Signal-Layer
  intelligence panel: brief, top signals, recommendations, provider health) and `modes_world.tsx` (the mode
  wrapper that mounts it). Batched because they're one feature. `world-intelligence.tsx` hit the **same
  optional-prop pattern** as the `Icon` fix: a local `SubH({ children, style })` renders `style={style}`
  (an `undefined` style is a no-op in React), so `style` is optional — two call sites omit it. Marked it
  optional. `modes_world.tsx` needed **zero** changes — its earlier errors were all downstream of the
  `Icon` contract gap fixed in #386, so stripping the directive was enough. 9 non-test source modules remain.
- **Verified (automated):** `tsc --noEmit` clean; frontend **vitest 73 passed**; `agents/web/v2` bundle
  **byte-identical** (rebuilt to confirm — `hud-v2-build` guard matches). No backend/route change.
- **⚠️ Needs you:** the World Intelligence overlay (press `W` in the HUD) reads the optional external
  Signal-Layer service on `:8787` — its live data path is owner-runtime-gated like every panel, but the
  typing change here is compile-time only and behaviour-identical.

### HUD — type `world_app.tsx` + fix the `Icon` optional-props contract (CDX-9 typing pass)
- **What:** removed `@ts-nocheck` from `frontend/src/world_app.tsx` (the "World Intelligence" overlay shell —
  the `W`-key fullscreen panel that wraps `<App/>` and mounts `WorldIntelligenceMode`). The two tsc errors it
  surfaced were a real **contract gap** in the shared `Icon` primitive (`primitives.tsx`): `Icon` is
  `function Icon({ d, size, sw })` where `size`/`sw` both have runtime fallbacks (`size||16`, `sw||1.6`) —
  genuinely optional — but once `primitives.tsx` was type-checked (PR #384), TS inferred all three params as
  *required*, so any caller omitting `sw`/`size` (which is most of them) failed. Marked `size`/`sw` optional
  in `Icon`'s signature — the honest contract. This is a **one-line fix that unblocks every `Icon` caller
  across the HUD**, not just `world_app`. Type-only, so the bundle is byte-identical.
  11 non-test source modules remain on `@ts-nocheck`.
- **Verified (automated):** `tsc --noEmit` clean; frontend **vitest 73 passed**; `agents/web/v2` bundle
  **byte-identical** (rebuilt to confirm — `hud-v2-build` guard matches). No backend/route change.
- **⚠️ Needs you:** nothing — compile-time only. (`Icon` rendering is unchanged; the fix only relaxes the
  *type*, the runtime already defaulted `size`/`sw`.)

### HUD — type `network.tsx` + remove a dead `_wrap` write (CDX-9 typing pass)
- **What:** removed `@ts-nocheck` from `frontend/src/network.tsx` (the agent-mesh "network brain"
  visualizer). The one tsc error it surfaced was a real **dead write**: `NetworkBrain._wrap = el` — a
  `ref` callback stashing the wrapper DOM node onto the component *function object*, never read anywhere
  in the codebase (grep-confirmed across `src/`). Removed the whole dead `ref` callback rather than papering
  over it with a cast — that dead-wiring is exactly the drift CDX-9 exists to catch. The production
  minifier had **already** eliminated the write, so the bundle is byte-identical despite the source change.
  12 non-test source modules remain on `@ts-nocheck`.
- **Verified (automated):** `tsc --noEmit` clean; frontend **vitest 73 passed**; `agents/web/v2` bundle
  **byte-identical** (`index-CwY1ye9O.js`, rebuilt to confirm — `hud-v2-build` guard matches). No
  backend/route change.
- **⚠️ Needs you:** glance at the agent-network panel once (it renders the orbiting agent mesh) to confirm
  it still draws — purely to double-check the removed `ref` truly had no effect (it shouldn't; nothing read
  it). Compile-time + behaviour-identical otherwise.

### HUD — type the `data.ts` keystone + leaf modules (CDX-9 typing pass)
- **What:** removed `@ts-nocheck` from the **keystone** `frontend/src/data.ts` (the pure `V2` seed object
  every capability mode reads via `V2.<KEY>`) plus its barrel `ui.ts`, the shared `primitives.tsx` UI
  symbols, and `LiveSourceChip.tsx`. Typing `data.ts` is the unblock: the big components read off `V2`, so
  they couldn't be type-checked until the seed's own shape compiled clean. These 4 came off with **zero**
  added annotations — the literals/JSX already inferred correctly. 17→13 non-test source modules on
  `@ts-nocheck` (remaining: `app`/`shell`/`gap`/`cockpit`/`modes`/`modes2-4`/`modes_world`/`voice`/
  `network`/`world-intelligence`/`world_app`, to be done smallest-tsc-error-first, each its own PR).
- **Verified (automated):** `tsc --noEmit` clean; full frontend **vitest 73 passed** (unchanged — types
  erase, behaviour-identical); `agents/web/v2` bundle **byte-identical** (`index-CwY1ye9O.js`, rebuilt to
  confirm — the `hud-v2-build` guard matches). No backend/route change.
- **⚠️ Needs you:** nothing — compile-time only.

### HUD — type the whole api/ data layer (CDX-9 typing pass)
- **What:** removed `@ts-nocheck` from **all** of `frontend/src/api/` — `actions.ts`, `signalLayer.ts`,
  and `live.ts` — so the entire HUD data layer is now type-checked. `actions.ts` declares response
  interfaces (`NorthStarMetrics`, `KillSwitchState`, `AuditVerifyResult`, `PluginList`, …) threaded
  through the client's existing `apiGet<T>` generic, so a backend shape change is caught at the call
  boundary (the core CDX-9 "live-wiring hides shape drift" complaint). `signalLayer.ts` got a typed
  `WorldIntelligence` return + a `PromiseRejectedResult` guard. `live.ts` keeps `any` only at its genuine
  heterogeneous ingestion points (varied backend shapes normalized onto `V2` before render — tightening
  those wants `data.ts` typed first). 22→19 source modules on `@ts-nocheck`.
- **Verified (automated):** `tsc --noEmit` clean; full frontend **vitest 73 passed** (unchanged — types
  erase, so it's behaviour-identical); `agents/web/v2` bundle is **byte-identical** (no rebuild needed —
  the `hud-v2-build` guard matches). No backend/route change.
- **⚠️ Needs you:** nothing — compile-time only. The big HUD components (`app.tsx`/`gap.tsx`/`modes*.tsx`)
  remain on `@ts-nocheck`; those are the heavier, incremental follow-ups (each its own PR).

### Security — cover the audit-log query/read path (coverage hardening)
- **What:** `security/audit.py` `query()` — the read path the admin audit page uses to reconstruct
  `SecurityEvent`s (incl. findings) from the tamper-evident chain — was **untested** (81% file). Added a
  round-trip test (log → query, newest-first, findings reconstructed with the right type/threat/offsets)
  and a filter test (`event_type` / `since` / `limit`). The round-trip also **re-confirms AUD-12**: the
  stored `matched_text` comes back as the `[REDACTED:<pattern>]` marker, never the raw secret.
- **Verified (automated):** `tests/test_audit_hardening.py` (+2) — covers audit.py lines 134-169. Full
  suite **3,036 passed**; `ruff` + `bandit` clean. No behaviour change.
- **⚠️ Needs you:** nothing — offline coverage hardening of an already-correct read path.

### Security — cover the guardrails scan/redact/block + streaming path (coverage hardening)
- **What:** `security/guardrails.py` (the LLM-call wrapper that scans prompts/responses for secrets &
  PII) was 77% covered — the **entire `generate_stream` path was untested**, along with the system-prompt
  scan and the redact/block-on-finding branches. Added tests that drive a real finding (an email PII)
  through **REDACT** (input + system + output all scrubbed) on both `generate` and `generate_stream`,
  assert **BLOCK** raises `SecurityBlockError`, and cover the defensive unknown-mode passthrough.
- **Verified (automated):** `tests/test_guardrails_generate_kwargs.py` (+4) — covers guardrails.py lines
  68/80/99-120. The existing kwarg tests only ran WARN-mode passthrough; these exercise the parts that
  actually act on a finding. Full suite **3,034 passed**; `ruff` + `bandit` clean. No behaviour change.
- **⚠️ Needs you:** nothing — offline coverage hardening of an already-correct redaction path.

### Security — pin the SSRF IPv6-mapped/embedded-IPv4 bypass defense (coverage hardening)
- **What:** `security/ssrf.py` was the lowest-covered file in the safety-critical core (85%) — and the
  uncovered branches were exactly the **IPv6-mapped / embedded-IPv4 unwrap** logic (`::ffff:a.b.c.d`,
  `::a.b.c.d`), the notation attackers use to wrap `169.254.169.254` / `127.0.0.1` / RFC1918 in IPv6 and
  slip past a naive host filter. I **scratch-simulated** every bypass first to confirm the filter actually
  blocks them (it does — no bug; mapped-public still passes), then added tests that **pin** that property
  so a future refactor can't silently reopen the hole.
- **Verified (automated):** `tests/test_ssrf.py` (+5) — `is_private_ip` unwraps mapped loopback/metadata/
  RFC1918 (and the deprecated `::a.b.c.d` form) → blocked, mapped-public → allowed, garbage → False;
  `resolve_and_validate` + `check_ssrf` block bracketed-IPv6 metadata/private URLs; empty `getaddrinfo`
  fails closed. Covers ssrf.py lines 38/41/47-48/52/80-82/98-99. Full suite **3,030 passed**; `ruff` +
  `bandit` clean.
- **⚠️ Needs you:** nothing — pure offline security-coverage hardening; behaviour unchanged (it was already
  correct, just untested).

### HUD — visible LIVE/SEED chip per mode (CDX-9 slice)
- **What:** the HUD modes stream real backend data when a source responds and fall back to a seeded mock
  otherwise — but nothing told you which, so live-wiring quietly hid shape drift. A new `LiveSourceChip`
  (driven by a pure `liveSourceState()` over the existing `useLiveModes()` live-map + the demo flag) now
  labels each mode **LIVE** (green, real backend) / **SEED** (amber, demo/mock) / hidden (mode has no
  backend source or nothing's showing). Rendered once at the workzone in `app.tsx`.
- **Verified (automated):** `frontend/src/test/live-source-chip.test.tsx` (+7) — the state logic (live /
  seed / null across the cases) and the chip render (LIVE / SEED / nothing). Full frontend **vitest 73
  passed**; `tsc --noEmit` clean; HUD-v2 parity green; `agents/web/v2` rebuilt + committed.
- **⚠️ Needs you (live pixels — CDX-9):** open each mode in a real browser and confirm the LIVE/SEED chip
  reads correctly (LIVE when a backend source is up, SEED under DEMO) and sits well in the layout. *(The
  larger CDX-9 half — OpenAPI-generated types + removing `@ts-nocheck` per module — is left as its own
  slice, not attempted here.)*

### Cleanup — per-agent call timeout is now a tunable setting (CDX-6)
- **What:** `_call_agents_parallel` hard-coded a `120.0`s per-agent LLM-call timeout — one invisible
  ceiling shared across chat / deep-research / autonomy / eval. Extracted to
  `Orchestrator._agent_call_timeout()`, which reads the **`agents.agent_timeout_seconds`** setting
  (default 120), clamps it to **≥1s**, and falls back to 120 on a non-numeric value so a bad config can
  never disable the timeout. The ceiling is now visible and per-context tunable.
- **Verified (automated):** `tests/test_orchestrator_process_record.py` (+4) — default 120, honors a set
  value, clamps 0/negative → 1s, and a non-numeric value → safe 120 (never raises). Full suite **3,025
  passed**; `ruff` + `bandit` clean. Behavior-preserving by default (still 120s until you set it).
- **⚠️ Needs you:** nothing. Optional: set `agents.agent_timeout_seconds` lower for snappy chat or higher
  for long deep-research runs. *(Full per-task budget-object integration into the chat pipeline remains a
  larger refactor — flagged, not attempted, since the request pipeline isn't safely extractable yet.)*

### Privacy — CLI "forget me" now erases memory at rest (AUD-2 completeness)
- **What:** the **CLI** forget (`python -m agents.core.data_purge --confirm`) now defaults to
  `memory=True`, so it erases the memory subsystem at rest (knowledge graph / entities / decay stores,
  embedding cache, session transcripts) — closing a real **PII-retention gap**. AUD-2 (#315) had brought
  only the `/api/admin/forget` *endpoint* to parity; the offline CLI still left memory behind. A
  `--no-memory` escape mirrors the existing `--no-backup`. Also documents (in the module docstring) that
  the backup-first snapshot is plaintext PII until a backup key is set (AUD-1) — secure/remove it after a
  forget, or use `--no-backup`.
- **Verified (automated):** `tests/test_data_purge.py` (+1) — the CLI erases the memory stores by default
  and `--no-memory` leaves them; the function-level memory purge stays covered by
  `tests/test_data_purge_memory.py` (I dropped the redundant duplicates). Full suite **3,027 passed**;
  `ruff` + `bandit` clean.
- **⚠️ Needs you:** nothing code-side. *Operational note:* the live Qdrant/Neo4j wipe is best-effort via
  each store's `clear()` (the endpoint clears live stores first); a true external-service purge for those
  remains an ops step on a real deployment.

### V-track — reality harness now proves the kernel capability-token rail
- **What:** a fourth **hermetic** reality case completes the proof of the Action-Kernel's *gate-1*: the
  **capability-token path** (alongside the kill-switch rail from the prior PR). With a real
  `CapabilityBroker`, a valid minted token clears the kernel gate (the action reaches policy), and a
  missing/unknown token makes `kernel.authorize` return **DENY** ("no valid capability token"). A green
  probe promotes `component:capabilities` to **VERIFIED**. Both halves of the kernel's first gate
  (kill-switch + capability) are now harness-backed.
- **Verified (automated):** scratch-simulated first (valid→queue, missing→deny). `tests/test_reality_harness.py`
  (+1, now 8): the seeded-cases test asserts both `component:kill_switch` and `component:capabilities`
  promote; a focused test runs the capability case in isolation. Full suite **3,020 passed**; `ruff` +
  `bandit` clean — bandit flagged the deliberately-invalid token literal as a hardcoded-credential false
  positive (B106), so it's bound to a named variable rather than growing the baseline (the trivial-refactor
  fix, since it's avoidable unlike the status_sync subprocess findings).
- **⚠️ Needs you:** nothing — hermetic, offline. (Live keyed per-capability cases remain the owner-gated
  nightly-lane follow-up.)

### V-track — reality harness now proves the Action-Kernel kill-switch rail
- **What:** a third **hermetic** reality case (`reality_harness.py:CASES`) proves the most safety-critical
  Track-K rail end-to-end with **real primitives** — not a mock: an engaged `KillSwitch` makes
  `kernel.authorize` return **DENY**, and disengaging lets the same action past the kill-switch gate
  (it reaches policy). A green probe promotes `component:kill_switch` to **VERIFIED** in the V2 registry.
  Extends the harness beyond the egress rail to the kernel's deny path, advancing Gate-V ("nothing
  VERIFIED without a green harness").
- **Verified (automated):** scratch-simulated against the real `KillSwitch`/`authorize` first (engaged→deny,
  disengaged→queue, and the **live kill-switch left untouched** — the probe uses a throwaway temp store).
  `tests/test_reality_harness.py` (+1, now 7): the kill-switch case passes + promotes, and a guard asserts
  `KillSwitch().is_halted("global")` stays False (isolation proof). Full suite **3,019 passed**; `ruff` +
  `bandit` clean (mkdtemp is the safe-tmp pattern — no new findings).
- **⚠️ Needs you:** nothing — it's a hermetic, offline proof. (The *live*, keyed per-capability cases remain
  the owner-gated nightly-lane follow-up, as before.)

### Tooling — `scripts/status_sync.py` ends the STATUS.md count drift (CDX-5)
- **What:** a small CLI that derives the two STATUS.md header numbers that drift on nearly every PR —
  the **test count** (`pytest --collect-only`) and the **HTTP-route count** (the parity snapshot) — and
  either `--check`s STATUS.md against them or `--write`s them in place. Replaces the hand-bumped "~N
  passed" step (which had already silently drifted to **327 routes / 3,011 tests**; the tool corrected
  it to **328 / 3,024**). Closes the "Remaining" half of CDX-5. Deliberately **not** a blocking CI gate
  (the header `~` signals approximate) — `--check` is an optional nudge, not a merge wall.
- **Verified (automated):** `tests/test_status_sync.py` (+7) — route count matches the snapshot, the
  STATUS rewrite is anchored (touches only the two tokens, leaves version strings / "45 routers" prose
  intact), each token rewrites independently, and the live STATUS.md parses. The heavy `count_tests()`
  (shells out to a full collection) is left out of the unit tests on purpose. Dogfooded end-to-end
  (`--write` then `--check` clean). Full suite + `ruff` + `bandit` clean.
- **⚠️ Needs you:** nothing — pure dev tooling. Optionally run `python scripts/status_sync.py --check`
  before a release to confirm STATUS.md isn't stale.

### HUD — north-star meter now surfaces the P1 proactive metrics
- **What:** the ObserveMode **`NorthStarMeter`** (`modes2.tsx`) gained a third **PROACTIVE** row that
  renders the metrics shipped in #369/#370 but previously invisible in the HUD: **done overnight** +
  **night share** (`night_shift.done` / `.pct`) and **surfaced/proposed** + **accept rate**
  (`proposal_funnel.surface_rate` / `.accept_rate`). Closes the value loop — the proof-gap numbers are
  now *seen*, not just served on `/api/metrics/north-star`. Same single-user honesty as the rest of the
  meter: a null block renders **"—"**, never a fabricated `0%`.
- **Verified (automated):** `frontend/src/test/trust-analytics.test.tsx` (+2) — the proactive row
  renders night-share 50% / surface 75% / accept 67% from a populated payload, and honest "—" when the
  blocks are null. Full frontend **vitest 66 passed**; `tsc --noEmit` clean; `agents/web/v2` rebuilt +
  committed (the `hud-v2-build` guard). Frontend-only — no backend/route change.
- **⚠️ Needs you (live pixels — CDX-9):** open the HUD *Observe* mode and confirm the PROACTIVE row
  shows the overnight count + night share + funnel rates once there's real autonomy activity.

### HUD — "Today in Jarvis" cockpit panel (P1 G1 UI)
- **What:** a Console *Autonomy & Agents* panel (`TodayPanel`) that renders the unified-timeline
  endpoint (`GET /api/dashboard/today`): each row is a **did** (autonomy action, green) or **learned**
  (memory fact, accent) tag + label + local time, newest-first, under a `"N did · M learned"` header.
  Closes the UI half of P1 G1 (the backend feed shipped in the prior item).
- **Verified (automated):** `frontend/src/test/today-panel.test.tsx` (+2, fetch-mocked) — did/learned
  rows + summary render, and a clean empty state. Full frontend **vitest 64 passed**; `tsc --noEmit`
  clean; backend HUD-v2 parity green; `agents/web/v2` rebuilt + committed (the `hud-v2-build` guard).
- **⚠️ Needs you (live pixels — CDX-9):** open Console → *Autonomy & Agents* in a real browser after
  some autonomy + a few remembered facts, and confirm the did/learned items interleave by time and the
  header count matches.

### Dashboard — P1 unified "Today in Jarvis" timeline (proof-gap 3/3)
- **What:** new `memory/timeline.py:build_unified_digest(queue, memory_entries, …)` fuses what Jarvis
  **did** (autonomy tasks that reached `done`) and what it **learned** (new / updated memory facts &
  preferences) into **one timestamp-ordered feed** — closing the gap where the task recap
  (`autonomy/digest.py`) and learnings (`memory/digest.py`) lived in separate places. Served at
  **`GET /api/dashboard/today?days=1`** (`user_guard`'d — it surfaces personal facts; `days` clamped
  1–30). Pure builder over existing rows (a `TaskQueue` + the SQLite fact store via `MemoryStore()`):
  no new capture, no schema. This closes the **third and last P1 proof-gap** — all three are now done.
- **Verified (automated):** `tests/test_timeline.py` (+9) — fusion + newest-first ordering, window
  exclusion, `days` widening, `limit` truncation (counts reflect the *full* in-window set), honest
  empty/None state, unparseable-timestamp rows kept (never dropped), and the endpoint (fuse + 422
  clamp + 503). Route-surface / OpenAPI / route-auth / HUD-v2 parity snapshots reseeded (one route
  added: `GET /api/dashboard/today` → `user` guard, cockpit surface). **Full suite 3,011 passed**;
  `ruff` + `bandit` clean.
- **⚠️ Needs you (CDX-9 — live pixels, deferred):** this PR is **backend-only** — there's no HUD panel
  yet (a *cockpit* "Today" panel reading this endpoint is the follow-up UI slice, same rhythm as the
  feedback/onboarding panels). Eyeball the data now: `curl localhost:<port>/api/dashboard/today | jq`
  after some autonomy + a few remembered facts, and confirm the did/learned items interleave by time.

### Metrics — P1 night-shift north-star split ("works while you sleep" as a number)
- **What:** `compute_north_star` now returns a **`night_shift`** block — `{done, pct, window}` —
  measuring, of the accepted actions, how many **completed during the local night window**. It buckets
  each `done` task by the *local* hour of its `updated_at` (the stored UTC stamp converted to the
  server's zone — the user's clock on a single-user box), reusing the worker's **`is_night_window()`**
  so the split matches the same window that gates the overnight tier caps. The endpoint threads the
  configured `autonomy.night_start`/`night_end` (default 23→6). Turns the headline P1 claim into a
  reported number. Auto-exposed via `GET /api/metrics/north-star`; docs in `docs/METRICS.md`. Second of
  the three P1 proof-gaps.
- **Verified (automated):** `tests/test_north_star.py` (+3) — a 3-accepted split (02:00 + 23:00 → night,
  14:00 → day ⇒ `done`=2, `pct`=2/3), a custom-window case, and an empty `pct`=null honest case. The
  helper writes each timestamp as today's local hour stored back as UTC, so the split is **TZ-robust**
  (deterministic in CI's UTC and on a dev box alike). **Full suite 3,002 passed**; `ruff` + `bandit`
  clean. Backend-only — no HUD build artifact touched.
- **⚠️ Needs you:** nothing owner-only. The night window is the server's *local* clock — if you run the
  box in a different TZ than you sleep in, set `autonomy.night_start`/`night_end` to match. Eyeball:
  `curl localhost:<port>/api/metrics/north-star | jq .night_shift` after some overnight autonomy.

### Metrics — P1 proposal-funnel diagnostic on the north-star
- **What:** `compute_north_star` now also returns a **`proposal_funnel`** block — a *cohort*
  over the proposals **created** in the window: `proposed → surfaced` (a decision card reached
  the inbox / `pushed`) `→ accepted` (`done`) / `rejected` / `pending`, plus `surface_rate` and
  `accept_rate`. It localizes *where* a low north-star comes from (too few proposed? proposed
  but never surfaced? surfaced but rejected?). Auto-exposed read-only via
  `GET /api/metrics/north-star` — no new endpoint, no new storage, pure function over the
  existing autonomy `TaskQueue`. First of the three P1 proof-gaps (the pack that moves the
  north-star). Docs in `docs/METRICS.md`.
- **Verified (automated):** `tests/test_north_star.py` (+3) — a 4-proposal cohort
  (2 accepted / 1 rejected / 1 pending, 2 surfaced; `accept_rate`=2/3, `surface_rate`=0.5) with a
  30-day-old proposal proving the created-in-window cohort excludes it; plus empty-honest and
  None-queue cases. **Full suite 2,999 passed**, `ruff` + `bandit` clean. Backend-only — no HUD
  build artifact touched.
- **⚠️ Needs you:** nothing owner-only here — it's pure aggregate metrics over existing rows. If
  you want to eyeball it, `curl localhost:<port>/api/metrics/north-star | jq .proposal_funnel`
  after some real autonomy activity and sanity-check the drop-off story against what you saw.

### HUD — Onboarding panel (H23.20 UI)
- **What:** a Console *Observe* panel that drives the first-run wizard: it reads
  `GET /api/onboarding/wizard` and renders the ordered steps (intro → model → say-hello →
  autonomy-budget) with **done/pending** state + progress + the **cold-start hint** (shown when
  no model backend is reachable), and a per-step **done** button records the funnel event
  (`POST /api/onboarding/funnel`) so completion **persists across reloads**. Closes the UI half
  of H23.20 (backend already shipped).
- **Verified (automated):** `frontend/src/test/onboarding-panel.test.tsx` (+2, fetch-mocked) —
  steps render with completed-marking + the mark-done control, and the cold-start hint surfaces.
  Full frontend **vitest 62 passed**; `tsc --noEmit` clean; backend HUD-v2 parity green;
  `agents/web/v2` rebuilt + committed.
- **⚠️ Needs you (live pixels — CDX-9):** on a fresh install, open Console *Observe* and confirm
  the onboarding steps + cold-start hint render and that marking a step done sticks across reload.

### HUD — Feedback / NPS panel (H23.21 UI)
- **What:** a Console *Observe* panel that surfaces the design-partner feedback loop: it reads
  the **NPS summary** (`GET /api/feedback/summary`, admin — promoters/detractors + per-kind counts
  + recent comments) and carries a **submit form** (score 0–10 + comment → `POST /api/feedback`).
  Closes the UI half of H23.21 (the backend feedback store + endpoints already shipped).
- **Verified (automated):** `frontend/src/test/feedback-panel.test.tsx` (+2, fetch-mocked) — the
  NPS/promoters/detractors + a recent item render and the submit control is present; clean
  empty-state. Full frontend **vitest 60 passed**; `tsc --noEmit` clean; backend HUD-v2 parity
  green; `agents/web/v2` rebuilt + committed (the `hud-v2-build` guard).
- **⚠️ Needs you (live pixels — CDX-9):** open Console *Observe* in a real browser, submit an NPS
  score, and confirm it appears in the summary. (Recruiting the actual design partners is your call.)

### K3 (recursion-depth cap) — sub-agent delegation can't tower up unbounded
- **What:** `SubAgentManager` already capped how *wide* an agent forks (concurrency); this caps
  how *deep* — a sub-agent that spawns a sub-agent that spawns a sub-agent now hits a
  **recursion-depth cap** (OWASP unbounded-consumption). Depth is inferred from the recorded
  parent-chain, so no runner change is needed. Default **8** (a real guard out of the box;
  configurable via the `autonomy.max_subagent_depth` setting; `None`/≤0 = unbounded).
- **Verified (automated):** `tests/test_subagent_depth.py` (+4) — a deep chain is rejected at the
  cap with a clean `recursion_depth_cap` reason, flat (top-level) spawns never hit it, `None` is
  unbounded, and the `≤0 → unbounded` normalization + default-8 hold. Existing subagent tests still
  green. Full suite **2,996 passed**; ruff + bandit clean.
- **⚠️ Needs you:** nothing urgent — the default 8 is deep enough for any real delegation. If you
  build deeply-nested agent workflows, raise `autonomy.max_subagent_depth`.

### K3 (per-task wall-time budget) — a task can't run forever
- **What:** the autonomy worker's `TaskExecutor` now supports a per-task **wall-time budget**
  (`JARVIS_TASK_MAX_SECONDS`). A task whose handler overruns is **cancelled** at the dispatch
  point and returns a clean `{"status":"failed","reason":"wall_time_budget_exceeded"}` — an
  OWASP unbounded-consumption guard. **Default-off** (unset / ≤0 = unbounded → byte-identical).
- **Verified (automated):** `tests/test_executor_budget.py` (+5) — unbounded default runs
  normally, a within-budget task completes, an **overrunning task is cancelled** (its handler
  body provably does *not* finish) and returns the clean failed result, non-dict results still
  wrap, and the env parsing handles blank/zero/garbage. Full suite **2,992 passed**; ruff + bandit clean.
- **⚠️ Needs you:** if you enable `JARVIS_TASK_MAX_SECONDS`, pick a value above your **legitimate**
  longest task (deep-research / long autonomy runs can be minutes) — too low will cancel real work.
  The token + recursion-depth budget dimensions are still pending (they need handler-level hooks).

### HUD — Track-K safety panels (H23.3 + this session's backends)
- **What:** the Console *Trust* section now surfaces the kernel safety controls so an operator
  doesn't need `curl`. The **kill-switch one-tap** (HALT-ALL / disengage) was already there;
  this adds **`KernelMetricsPanel`** (`GET /api/metrics/kernel` — grant/queue/deny tallies + the
  recent denials with reasons; a default-off hint when the meter is empty) and **`LoopBreakerPanel`**
  (`GET /api/security/loop-breaker` — tripped/closed + threshold/window, with a **reset** button shown
  only when tripped). Frontend-only — all three endpoints already shipped this session.
- **Verified (automated):** `frontend/src/test/kernel-safety-panels.test.tsx` (+4, fetch-mocked) —
  verdict tallies + a denial render, the empty-meter hint, reset-only-when-tripped, no-reset-when-healthy.
  Full frontend vitest **58 passed**; `tsc --noEmit` clean; backend HUD-v2 parity guard still green.
- **⚠️ Needs you (live pixels — CDX-9):** open the Console *Trust* section in a real browser and
  confirm the three panels render and the buttons work — with `JARVIS_ACTION_KERNEL=1`, engage the
  kill-switch and watch the deny tally tick up on the kernel panel; trip the loop breaker (or its test
  hook) and confirm **reset** closes it. This is the operator cockpit for everything Track-K — worth a
  real look.

### Gate-K observability — `GET /api/metrics/kernel`
- **What:** now that every privileged action crosses `kernel.authorize`, there's a single
  place to see what the kernel is doing. An in-process meter tallies **grant/deny/queue per
  action kind** + a deny-rate + the **recent denials with reasons** (so a halt / runaway /
  over-budget is visible), served at `GET /api/metrics/kernel` (open, like the north-star /
  capabilities meters). In-memory only (resets on restart; the IntentLog audit chain is the
  durable record). **No runtime behavior change** — it only tallies what already happens, and
  stays empty until `JARVIS_ACTION_KERNEL` is on (brokers/routes don't call `authorize` when off).
- **Verified (automated):** `tests/test_kernel_metrics.py` (+5) — meter unit (record/snapshot/
  reset, bounded denials ring, unknown-verdict ignored), the kernel tallies grant/queue/deny
  through a real `authorize` (incl. a halted-kill-switch deny captured with its reason), and the
  endpoint returns the snapshot. Full suite **2,987 passed**; ruff + bandit clean; route/auth/
  OpenAPI parity snapshots reseeded (+1 open route).
- **⚠️ Needs you:** nothing — pure observability. During manual testing with the kernel flag on,
  `GET /api/metrics/kernel` is the quickest way to confirm the kill-switch/loop-breaker/budget
  denials are firing as expected (and a HUD panel for it is a natural future add).

### K3 (loop-breaker slice) — loop circuit breaker bound to the agent-action path
- **What:** the kernel's loop-wide circuit breaker (`LoopDetector`, an OWASP
  unbounded-consumption guard) is now wired in. The orchestrator owns one shared
  `self.loop_detector`, and the autonomy coordinator binds it into the **broker-mediated**
  kernel — so with `JARVIS_ACTION_KERNEL=1`, a runaway agent that re-requests the **same**
  governed action (call/social/writeback/node/payment) past the threshold (default 10 in
  60s) is **denied** at the kernel front door. **Default-off.**
- **The key design call:** it is bound **only** to the broker path, **not** routes/egress/
  MCP/KG. The breaker keys on `action.kind`, and those paths legitimately repeat one kind
  (many egress calls, many KG writes), so a fleet-wide binding would **false-trip** on
  normal traffic. `make_action_kernel(orch)` (used by routes/egress) omits the detector;
  only the autonomy coordinator passes it.
- **Verified (automated):** `tests/test_kernel_loop_breaker_wave.py` (+5): trips on a
  runaway · counts **per-signature, not total** · the route/egress kernel never carries it
  (20 identical `kg.write` never trip) · a None detector is inert · a **real `CallBroker`
  end-to-end** refuses the runaway. Full suite **2,978 passed**; ruff + bandit clean.
- **⚠️ Needs you:** the breaker threshold is **10 identical governed actions in 60s** — a
  conservative default. During testing with the kernel flag on, confirm your **legitimate**
  workloads (e.g. a pipeline dispatching many `node.dispatch` subtasks) don't hit it; if
  they do, that threshold should become configurable (a tracked follow-up). The breaker
  stays open until reset — the API for that now exists: `GET /api/security/loop-breaker`
  (status) + `POST /api/security/loop-breaker/reset` (admin; **not** kernel-mediated, so a
  tripped breaker can't block its own reset). A HUD button for it is still a future add.

### V3 — cross-agent interface-contract drift gate
- **What:** a new CI gate (`tests/test_interface_contract_drift.py`) snapshots the **shared
  schemas that cross agent boundaries** — the kernel `Action`/`Decision`/`Capability`/`Budget`
  dataclasses (the contract every Gate-K-mediated action is built as), the `Verdict`/`Mediation`
  enums, and the A2A pydantic wire bodies — and fails CI if any field is added/removed/renamed/
  retyped or an enum value changes. Pure test/guard addition; **no runtime behavior change**.
- **Verified (automated):** the 3 guard tests pass; full suite **2,973 passed**; `ruff` + `bandit`
  clean. I also confirmed it actually bites (a field rename would fail with a precise message and
  the `--update` regenerate hint).
- **⚠️ Needs you:** nothing — it's a fleet-coordination safety net. (Remaining V3 tail: extending
  the readiness matrix to components/skills needs a booted fixture; subagent return-dict shapes
  are ad-hoc dicts that aren't statically introspectable.)

### K1 (wave-3, kg.write slice) — externally-driven KG writes route through the Action Kernel — **Gate-K COMPLETE** 🎉
- **What:** the 6 externally-driven `/api/kg/*` mutating HTTP handlers (entity upsert/delete,
  relation add/delete, fact add, ingest) now pass `kernel.authorize` (default-off). With
  `JARVIS_ACTION_KERNEL=1`, a halted kill-switch → **403**. This is the **last** Track-K
  slice: **every one of the 11 privileged action kinds is now KERNEL-mediated** — a halt
  uniformly denies payments, plugin egress, MCP writes, gated Tool-RPC, admin escalations,
  and external KG writes.
- **The boundary is the whole point** (workflow-verified, 8 agents, no blockers): only the
  *external* HTTP handlers are gated. The **internal, high-frequency** ingestion path
  (`IncrementalKGUpdater.ingest` from `orchestrator._record_interactions`, `seed_graph`,
  reflection) writes graph methods **directly** and is **never** gated — so **a halt does
  NOT freeze per-turn memory**. A dedicated test pins this: while halted, external
  `/api/kg/ingest` returns 403 *and* internal `kg_updater.ingest` / `graph.add_entity` still
  write. `memory.remember` (vector write), `/consolidate` (plan-only), `/decay/forget`
  (ACT-R op) are not KG writes → intentionally out of scope.
- **Verified (automated + scratch):** `tests/test_kg_kernel_wave.py` (+9) over real
  `InMemoryGraph`+`BiTemporalKG`+`IncrementalKGUpdater`+`KillSwitch`+`AutonomyPolicy`+real
  `make_action_kernel`: default-off byte-identical · clean→200 · halt→403 on all 6 handlers
  · **boundary proof** · disengage recovers · presented-bad-token→403 · deny-precedes-lookup
  (403 not 404) · keys-only payload (no PII values). The action-auth matrix proves `kg.write`
  routes through the kernel when on / not when off. Full suite green (2,970 passed).
- **⚠️ Needs you:** with `JARVIS_ACTION_KERNEL=1`, engage the kill-switch and confirm an
  `/api/kg/*` write (e.g. `POST /api/kg/entities`) returns 403 **while normal conversation
  still builds memory** (the internal KG keeps updating per turn — this is the critical
  boundary; please verify a real chat still remembers facts during a halt). Then disengage
  and confirm external KG writes resume. Note no-token requests are still allowed by design
  (wave-4b/K2 makes capability tokens mandatory).

### K1 (wave-4a) — admin kill-switch + capability-issue route through the Action Kernel (B1 structural)
- **What:** the two admin escalation routes — engaging the kill-switch and minting a
  capability token — now pass `kernel.authorize` **in addition to** today's `admin_guard`.
  With `JARVIS_ACTION_KERNEL=1`: a halted kill-switch (or a *presented* capability token
  that lacks the named capability) → **403**; the clean path (unknown admin kind → policy
  QUEUE) is treated as **allow-through** so there's no approval-UX regression. **Default-off.**
- **Designed + adversarially verified by a workflow** (8 agents) that caught two real
  blockers before any code:
  - **Bootstrap lock-out:** if disengage were mediated, a halt would deny its own release
    and the operator could never recover. **Fix shipped:** *disengage bypasses the kernel*
    (stays `admin_guard`-only) — recovery always works. A test pins exactly this
    (halt → engage/issue 403, but disengage 200 → released → mint works again).
  - **Honest scope:** the `Capability` is K1-tolerant, so a *no-token* admin request still
    falls through (QUEUE→allow). So this is the **structural** half of B1 (route through the
    kernel + cross-check a *presented* token + kill-switch gate); making a token **mandatory**
    is **wave-4b/K2**. The PR/BACKLOG say so explicitly — I did **not** overclaim "closes B1".
- **Verified (automated + scratch):** `tests/test_admin_kernel_wave.py` drives the **real
  handlers** over a real `KillSwitch`+`CapabilityBroker`+`AutonomyPolicy`+real
  `make_action_kernel`: default-off byte-identical · clean→200 · halt→403 + disengage
  recovers · presented-bad-token→403 · each handler emits its own kind. The action-auth
  matrix proves both admin kinds route through the kernel when on / not when off. Full
  suite green (2,961 passed; the last kernel xfail scaffold is now a real pass).
- **⚠️ Needs you:** with `JARVIS_ACTION_KERNEL=1`, (1) confirm engaging the kill-switch and
  minting a capability still work normally (200) on a clean system; (2) engage a halt, then
  confirm a *second* engage and a capability-mint return 403 **but disengage still works**
  (this is the safety-critical recovery path — please exercise it for real); (3) note that a
  no-token admin request is still allowed today by design — wave-4b will make tokens mandatory.

### K1 (wave-3, Tool-RPC slice) — gated Tool-RPC calls route through the Action Kernel
- **What:** a *gated* (external/mutating) Tool-RPC call — the path a sandboxed agent
  script uses to reach a mutating tool — now passes the **kernel** before it can even
  enqueue its approval task. With `JARVIS_ACTION_KERNEL=1`, a **halted kill-switch
  blocks gated Tool-RPC calls** (plus over-budget / runaway-loop denials), returning
  `kernel_denied`. Read-only inline tools are untouched (they run with no side effects).
  **Default-off** — zero change until enabled.
- **Verified (automated + scratch):** unit tests (flag-off skips the kernel even when
  bound, DENY blocks before the enqueue + audited, GRANT still enqueues, **read-only
  tools never consult the kernel**, args *keys* only in the payload — no values) **plus
  a real-primitives integration**: the production `kernel.authorize` over a real
  `AutonomyPolicy` + real `KillSwitch` — engage → not enqueued, release → enqueued. The
  action-auth matrix proves `tool.rpc` routes through the kernel when on / not when off.
  Full suite green (2,953 passed).
- **⚠️ Needs you:** Tool-RPC gated tools are an internal sandbox surface (no gated tool
  is registered by default beyond the `echo`/`time` read-only built-ins). When you wire
  a real gated tool, enable the kernel flag, engage the kill-switch, and confirm the
  gated call returns `kernel_denied` rather than enqueuing.

### K1 (wave-3, MCP slice) — MCP mutating tools route through the Action Kernel
- **What:** the MCP write surface (`MutatingRouteTool` — today just
  `route_memory_remember`, double-kill-switched off by default) now also passes the
  **kernel** after the existing per-identity gate. With `JARVIS_ACTION_KERNEL=1`, a
  **halted kill-switch blocks MCP writes** (plus over-budget / runaway-loop denials):
  identity proves *who*, the kernel decides *whether the write may run now*. A denial
  raises `MutatingKernelError`, is audited `refused-kernel`, and the write never runs.
  **Default-off** — zero change until enabled.
- **Verified (automated + scratch):** unit tests (flag-off skips the kernel even when
  bound, no-kernel writes, DENY blocks + audits + no write, GRANT writes, **identity
  failure precedes the kernel**, builder threads the kernel) **plus a real-primitives
  integration**: the production `kernel.authorize` over a real `AutonomyPolicy` + real
  `KillSwitch` — engage → write blocked, release → write runs. The action-auth matrix
  now proves `mcp.mutating` really routes through the kernel when on / not when off.
  Full suite green (2,947 passed).
- **⚠️ Needs you:** this surface is reachable only with BOTH `JARVIS_MCP_ROUTE_TOOLS`
  and `JARVIS_MCP_MUTATING_TOOLS` on (default off). During testing, with those + the
  kernel flag on, drive `route_memory_remember` over MCP, engage the kill-switch, and
  confirm the write is refused (`blocked by kernel`) with a `refused-kernel` audit row.

### K1 (wave-2) — plugin egress routes through the Action Kernel
- **What:** policy-passing plugin egress (an HTTP call the plugin's manifest already
  allows) now also passes the **kernel**. With `JARVIS_ACTION_KERNEL=1`, a **halted
  kill-switch blocks all outbound plugin calls** (plus over-budget / runaway-loop
  denials) — the manifest decides *where* a plugin may reach, the kernel can veto *that
  it reaches at all right now*. `http_client` stays fully decoupled: the orchestrator
  injects a plain `(plugin, method, url, host) → reason|None` hook bound to
  `kernel.authorize`. A buggy hook **fails open** (the manifest policy already ran), so
  the experimental gate can never brick egress. **Default-off** — zero change until enabled.
- **Verified (automated + scratch):** unit tests for the hook contract (deny blocks,
  allow passes, no-hook no-op, exception fails-open, **manifest block precedes the
  kernel**) + the production hook (default-off, deny-when-on, none-kernel-allows) **plus
  a real-primitives integration**: the production `kernel.authorize` over a real
  `AutonomyPolicy` + real `KillSwitch` — engage → egress raises `PluginEgressError`,
  release → egress allowed. The action-auth matrix now proves `plugin.egress` really
  routes through the kernel when on / not when off. Full suite green (2,938 passed); the
  old B3 xfail scaffold is now a real passing regression.
- **⚠️ Needs you:** during manual testing, set `JARVIS_ACTION_KERNEL=1`, engage the
  kill-switch from the HUD/API, and confirm a plugin that makes outbound calls (e.g. a
  weather/news plugin) is blocked while halted, then released. Also confirm the
  network-monitor panel records the blocked attempt (reason mentions the kernel).

### K1 (payment micro-wave) — payments route through the Action Kernel
- **What:** an *admissible* `request_payment` (one the mandate's hard caps already
  accept) now passes through `kernel.authorize`. A kernel **DENY** — kill-switch
  engaged, over-budget, or a runaway loop — refuses the payment **before** it can
  become `pending`; GRANT/QUEUE fall through to the existing always-approval flow.
  The kernel can only *add* a hard deny; it can't relax the rule that every payment
  needs explicit owner approval. The binding (`kernel/binding.py`) is now shared with
  the wave-1 brokers, so there's one definition of what the kernel front door is bound
  to. **Default-off** behind `JARVIS_ACTION_KERNEL` — zero behavior change until enabled.
- **Verified (automated + scratch):** unit tests (deny-before-pending, flag-off skips
  the kernel even when bound, inadmissible never reaches it, GRANT/QUEUE stay pending)
  **plus a real-primitives integration test**: the production `kernel.authorize` bound
  over a real `AutonomyPolicy` + real `KillSwitch` — halting the switch denies a
  payment (nothing becomes pending), releasing it lets the admissible payment proceed.
  Full suite green (2,928 passed).
- **⚠️ Needs you:** during manual testing, set `JARVIS_ACTION_KERNEL=1`, engage the
  kill-switch, and confirm a `request_payment` is refused (`kernel_denied`) and shows a
  `deny_payment` row in the payments audit; then release and confirm it goes to pending.

### H23.17 (slice) — i18n completeness gate
- **What:** `frontend/src/test/i18n-completeness.test.ts` fails CI if any locale (en/ro)
  is missing a key the reference has, has an extra key, or has a blank string. Runs in the
  existing CI vitest job.
- **Verified (automated):** ran the full frontend vitest suite locally — 54 tests pass
  including the 5 new i18n checks; en/ro are complete today.
- **⚠️ Needs you:** nothing. Remaining H23.17 slices (Playwright E2E, a11y, soak,
  browser/mobile matrix) are pending — E2E is feasible to build + simulate here.

### K2 — least-privilege capability set per agent (issuance)
- **What:** `kernel/capabilities.py` derives each agent's capability set from its declared
  config (plugins/channel/policy), and the orchestrator issues a scoped `CapabilityBroker`
  token per agent at boot (`orch.agent_capabilities`). Strict-local agents (frigga/ultron/
  howard) never get a cloud capability. **Inert** — nothing checks per-agent tokens yet
  (the per-action enforcement waves do), so zero behavior change.
- **Verified (automated + scratch):** unit tests (derivation least-privilege, real-broker
  issuance) + a scratch run over the **real 17-agent roster** confirming every agent gets a
  least-privilege token and the three local-only agents have no cloud cap.
- **⚠️ Needs you:** nothing yet. The enforcement half (B1 — admin actions require a
  capability; folding WorldView HMAC tokens) is a deliberate later wave.

### H23.6 — minimal taint flag + kernel escalation (indirect-injection guard)
- **What:** `security/taint.py` marks content from untrusted sources (web/OSINT/RSS/inbound)
  as tainted; the action kernel **escalates a tainted action from GRANT → QUEUE** (approval),
  so injected content can't auto-execute. Default-off effect: only fires for actions
  explicitly carrying the taint flag (nothing marks them yet — see pending).
- **Verified (automated + scratch):** unit tests (classifier, mark/is_tainted, kernel
  escalation) + scratch run against the **real** `AutonomyPolicy` confirming clean→GRANT,
  tainted→QUEUE.
- **⚠️ Needs you:** nothing yet — but note the producer side (marking ingested web/OSINT
  content tainted) and full data-flow propagation are a deliberate **deferred** follow-up,
  so this guard is mechanism-only until those land.

### B3 — strict-egress downgrade is now durably audited
- **What:** the `JARVIS_STRICT_EGRESS=0` escape hatch (allows a blocked-by-default egress
  host) was a *silent* log line. Now a decoupled audit sink (`http_client.set_egress_audit_sink`,
  wired by the orchestrator to an `AuditLogger` adapter) records a durable `EGRESS_DOWNGRADE`
  security event. No-op in strict mode (the default) — so no behavior change unless you've
  set `JARVIS_STRICT_EGRESS=0`.
- **Verified (automated):** unit tests — downgrade audits, strict mode blocks (no audit),
  no-sink no-op, a throwing sink never breaks egress, http_client stays decoupled from the
  security types. **Scratch:** real `AuditLogger` — a downgrade lands a durable row and
  `verify_chain()` returns valid (HMAC chain intact).
- **⚠️ Needs you:** nothing specific — but during testing, set `JARVIS_STRICT_EGRESS=0`,
  trigger a cross-host plugin call, and confirm the event shows in `GET /api/admin/audit`.

### K4 — kill-switch + credential-quarantine syscalls
- **What:** `kernel/syscalls.py` — `halt()` / `release()` promote the existing `KillSwitch`
  to a kernel call, and `inject_guarded()` makes secret injection **quarantine-aware** (while
  halted, injection is forced blocked regardless of approval). Folds H23.3. Composes existing
  primitives; no behavior change until a caller uses it.
- **Verified (automated):** unit tests — halt→quarantine→release, injection blocked while
  halted even when approved, `kernel.authorize` denies new grants when halted, audit emitted.
- **⚠️ Needs you:** the **one-tap kill-switch HUD control** (frontend) is not built yet — this
  is the backend syscall only. (HUD comes in the productionization-tail phase.)
