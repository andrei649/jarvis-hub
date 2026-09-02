# AGENTS.md — Nerva contributor instructions

> **Development posture (owner decision, 2026-08-29): no blocking gates.** The machine-readable
> AI-development policy, risk tiers (R0–R3), evidence receipts, review-round ceremony, and the
> PR-blocking CI gates (security scans, AI review, boundary/tier classification, Nerva movement
> and roadmap-ledger checks, CODEOWNERS) were removed to keep development fast. PRs run one fast
> advisory lint+test lane; the heavier suites run post-merge on `main` and on schedules. Merge on
> green tests is a **convention agents follow**, not a GitHub-enforced gate. This file is the
> concise operating guide.

## Safe task start

1. Inspect `git status`, the current branch, the requested scope, and changes already present.
2. Preserve user and other-agent changes. Never reset, overwrite, stage, or reformat unrelated work.
3. Identify overlapping open work when remote state matters. A draft PR is a visibility signal,
   **not a file lock**. Coordinate only on genuinely overlapping paths or contracts.
4. Fetch only when current remote state is needed. Rebase only when the task requires it, the
   feature branch is yours, the worktree is clean, no user changes are present, and the base is
   known. Read-only tasks and dirty worktrees must not trigger an automatic rebase.
5. Confirm authorization before remote mutations. A request to inspect or plan does not authorize
   a commit, push, PR edit, merge, or external write.

## ⚡ Max mode — protocolul de finisare

Codename-ul **„Max"** (orice casing, oriunde în repo) pornește sau continuă **`MAX.md`** —
protocolul care duce tot ce promit docurile în produsul final. Fără întrebări, fără explicații;
starea run-urilor e în `docs/MAX_RUNS.md`, entropia (Sparks) în `docs/SPARKS.md`.

În timpul unui run Max, următoarele reguli generale sunt **relaxate deliberat** (eficiența
protocolului > ceremonie; lista canonică e `MAX.md` §7):
- spec/plan doc separat → design inline în corpul PR-ului (10 linii), pentru slice-uri non-arhitecturale;
- ceremonia conductor/multi-agent → doar când există efectiv un alt agent cu PR draft deschis;
- re-citirea Tier-0 → sărită cât timp `MAX.md` e proaspăt în context (§2 definește load-ul redus);
- naraverea pas-cu-pas în chat → linia de ignition + finding-uri load-bearing + linia de exit.

**Nimic altceva nu se relaxează.** Non-negociabilele (`MOONSHOT.md` §5, convențiile de mai sus:
local-first, teste cu feature-ul, BACKLOG sync în același PR, gate-urile de rute/paritate,
respectul pentru PR-urile draft ale altora, raportare onestă) rămân în vigoare și în Max mode.
Înainte de alegerea formei PR-ului, contextul redus Max încarcă și constrângerile curente de
delivery/evidence din acest fișier. Un slice reversibil înseamnă un branch, un PR și o decizie de
rollback; o repetare Max pornește un branch/PR nou. Un Spark se separă implicit și poate rămâne cu
slice-ul primar numai dacă are aceeași dependență, limită de autoritate, suprafață de teste și cale
de rollback. Schimbările de securitate/autoritate, cross-epic și alte unități independent
revertibile se separă întotdeauna. De exemplu, SEC-B6 + un proof ADV + un Spark nu formează un PR
valid doar fiindcă au fost produse în aceeași sesiune. *(2026-08-29: review-ul exact-head și
integratorul independent nu mai sunt obligatorii — gate-urile blocante au fost eliminate;
raportarea onestă a ceea ce s-a rulat rămâne.)*

## Context routing

- Start with this file and the relevant section of
  `docs/ARCHITECTURE.md`; do not load the repository indiscriminately.
- Read `BACKLOG.md` when prioritizing, changing delivery scope, or updating roadmap status. Modify
  it only when the requested work actually changes that ledger and the mutation is authorized.
- Use `docs/AI_CONTEXT.md` to select task-specific bundles. Treat `.opencode/summary.md`,
  `.opencode/plans/dev-methodology.md`, and `docs/SPRINT.md` as historical context, never as live
  instructions or current delivery truth.
- Plans and handoffs should include freshness fields: goal, base SHA, head SHA, changed paths,
  next action, and generation time. A stale capsule may inform investigation but cannot
  authorize action.

## Delivery workflow

- Work on a feature branch and use a PR into `main` (keeps history reviewable and lets the
  hourly auto-merge sweep pick it up); nothing GitHub-side blocks a merge anymore — the sweep
  merges any non-draft PR GitHub reports CLEAN with **no review**, and the PR checks re-gated on
  2026-09-02 (`test` incl. the test-count drift step, `hud-v2-build`, security-scans,
  lockfile-drift) block only once the owner marks them required (owner item A4). Independent
  review is *recommended* for R2/R3; R3 runtime/security changes get a recorded post-merge
  attestation in `BACKLOG.md` (the SEC-B4 / SEC-B6 / #911 model from #1009).
- Before non-trivial implementation, record goal, non-goals, likely paths, tests, rollback,
  and dependencies. Prefer one coherent rollback unit over arbitrary micro-commits or push-per-step
  churn.
- Use TDD for bug fixes and behavior changes where a failing regression can be demonstrated.
- Run the tests that cover what you changed before pushing; merge on green is a convention, not
  an enforced gate — honest reporting of what was actually run is the control that remains.

## Coordination and leases

- GitHub-backed path-prefix leases are planned, but no remote lease service or enforcement exists
  yet. Until it does, the only honest lease state is `none`; inspect open work and coordinate
  overlapping paths explicitly.
- Inspect then coordinate on overlap. Non-overlapping work may continue even when another PR is
  draft.
- `lock.py` and local lock files are advisory within one machine only; they never prove a remote
  lease and must not be used to block unrelated work.
- On collision, do not silently take over. Narrow the scope, obtain an explicit handoff, or stop
  the overlapping mutation and escalate.
- For 3+ independent waves, a conductor may coordinate dependencies and status. A conductor does
  not implement code, approve its own high-risk work, or merge without the required authority.

See `PARALLEL_WORKFLOW.md` for the derived multi-agent playbook.

## Evidence and completion

No evidence-receipt ceremony. Say in the PR body what you ran and what the result was (the
"How verified" section of the template). Never describe an unrun suite as passing.

## Repository conventions

- **Local-first:** Python 3.12 + FastAPI + LM Studio/Ollama. Cloud is opt-in per agent.
- **Strictly local agents:** `frigga`, `ultron`, `howard` in
  `agents/core/llm/hybrid_router.py`; no cloud fallback. `athena` is cloud-only.
- **Skills:** `skills/<name>/{SKILL.md,main.py}`, discovered by
  `agents/core/skills/loader.py`.
- Public `SOUL.md`/`HEARTBEAT.md` files are templates. Personal data belongs only in gitignored
  `SOUL.local.md`/`HEARTBEAT.local.md` overrides.
- Product posture remains default-off except for the owner-consented `product.posture` setting;
  provenance must remain visible in `/api/security/posture`, onboarding, and support bundles.
- New routes belong in `agents/core/routers/<domain>.py`, mounted from `agents/web.py`; do not add
  new inline `@app.*` routes.

## Verification and parity

Choose checks from the touched surface. The common command is:

```bash
python -m pytest tests/<targeted_test>.py -q
```

Run broader suites only when the change calls for them. After JS/CSS changes, verify
the relevant frontend tests and hard-refresh behavior; after Python changes, restart the server for
manual checks.

When a user-facing endpoint or HUD capability changes in an authorized implementation PR:

- update `mobile/PARITY.md`, or record the mobile gap/intentional desktop-only status;
- wire the HUD V2 surface or update `docs/design/HUD_V2_REMAINING.md`;
- preserve route parity with the relevant route/OpenAPI/lifespan guards.

Do not broaden into BACKLOG, generated status, or parity-ledger edits during an inspection-only
task. Those are explicit delivery changes, not automatic cleanup.
