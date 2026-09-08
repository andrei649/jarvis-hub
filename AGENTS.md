# AGENTS.md — Nerva contributor instructions

> **Development posture.** Owner decision 2026-08-29 removed heavyweight blocking ceremony to keep
> development fast. **Updated 2026-09-09:** routine Nerva engineering is now explicitly
> **owner-out-of-loop**. `selfdev-policy.json` is the machine-readable autonomy contract and
> `scripts/selfdev_policy.py` is its stdlib-only validator/classifier. The hourly auto-merge workflow
> evaluates candidate PRs with the trusted policy/script already on `main`; normal product/code/test
> changes may merge unattended only after their reported automated checks have finished green, while
> the small root-of-trust control plane may not self-authorize changes to itself. This does not
> restore the old R0–R3 ceremony, review bureaucracy, or a blanket manual gate for Nerva work.

## Safe task start

1. Inspect `git status`, the current branch, the requested scope, and changes already present.
2. Preserve user and other-agent changes. Never reset, overwrite, stage, or reformat unrelated work.
3. Identify overlapping open work when remote state matters. A draft PR is a visibility signal,
   **not a file lock**. Coordinate only on genuinely overlapping paths or contracts.
4. Fetch only when current remote state is needed. Rebase only when the task requires it, the
   feature branch is yours, the worktree is clean, no user changes are present, and the base is
   known. Read-only tasks and dirty worktrees must not trigger an automatic rebase.
5. Confirm authorization before remote mutations. A request to inspect or plan does not authorize
   a commit, push, PR edit, merge, or external write. An owner directive for unattended development
   authorizes routine actions only inside the machine-readable self-development policy.

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
- For autonomous development/merge/deploy decisions, load `selfdev-policy.json` and use
  `scripts/selfdev_policy.py`; do not infer the root-of-trust boundary from prose or branch names.
- `BACKLOG.md` is the priority truth when prioritizing, changing delivery scope, or updating
  roadmap status. **Query it, do not load it** — it is ~957 KB (~176K tokens), and a whole read to
  answer "what is open" costs more than every other document here combined:
  `scripts/backlog.py counts | open | show <ID> | sections | find <regex>`. Listing every open row
  costs under 4 KB. Open the file itself only when you are *writing* to it, and then go to the one
  section `sections` names. Modify it only when the requested work actually changes that ledger and
  the mutation is authorized. The Hermes absorption ledger (1.4 MB of JSON) has the same rule and
  the same shape of tool: `scripts/ledger.py stats | clusters | list | show`.
- Use `docs/AI_CONTEXT.md` to select task-specific bundles. Treat `.opencode/summary.md`,
  `.opencode/plans/dev-methodology.md`, and `docs/SPRINT.md` as historical context, never as live
  instructions or current delivery truth.
- Plans and handoffs should include freshness fields: goal, base SHA, head SHA, changed paths,
  next action, and generation time. A stale capsule may inform investigation but cannot
  authorize action.

## Delivery workflow

- Work on a feature branch and use a PR into `main`. The hourly auto-merge sweep may merge any
  **non-draft** PR only when the same head satisfies all three conditions: GitHub reports `CLEAN`,
  the changed-file set is classified `autonomous_merge=true` by the trusted `main` copy of
  `scripts/selfdev_policy.py`, and **at least one automated check is reported with every reported
  check completed as success/neutral/skipped**. Pending, failed, cancelled, empty or unreadable
  check state does not merge. Branch names — including `nerva2/*` — are not manual gates anymore.
- A candidate touching a protected root-of-trust path is classified `control_plane` and skipped by
  unattended merge. That includes the self-development policy/classifier, **all GitHub workflows
  and actions**, Action Kernel/security roots, and the other paths named in `selfdev-policy.json`.
  Routine feature, refactor, test and documentation work outside that boundary does **not** wait for
  owner approval.
- The automated-check rule is enforced by the auto-merge workflow itself and does not depend on
  whether branch-protection settings happen to mark a check "required". The existing PR checks
  (`test` incl. test-count drift, `hud-v2-build`, security scans, `lockfile-drift`, and any future
  check that reports on the candidate SHA) therefore become real inputs to autonomous merge rather
  than advisory decoration. Do not claim a check is GitHub branch-protection-required unless the
  repository settings actually make it required.
- Before non-trivial implementation, record goal, non-goals, likely paths, tests, rollback,
  and dependencies. Prefer one coherent rollback unit over arbitrary micro-commits or push-per-step
  churn.
- Use TDD for bug fixes and behavior changes where a failing regression can be demonstrated.
- Run the tests that cover what you changed before pushing. Honest reporting of what was actually
  run remains mandatory even when merge/deploy is autonomous.

## Autonomous self-development boundary

- `selfdev-policy.json` expresses the owner's standing authorization for routine AI-operated
  engineering. Do not add an owner click merely because a change was AI-generated.
- The autonomous lane may create branches/PRs, implement code, update tests and merge eligible work
  once machine gates pass. Enforced independent AI review and autonomous release/canary/promote/
  rollback are recorded as **targets**, not claimed live until their #1054 enforcement slices land.
- The lane may **not** use the same change it is evaluating to weaken the classifier, root-of-trust
  path set, deployment credential isolation, rollback authority, any GitHub workflow/action,
  security boundary, Action Kernel, or emergency-stop/control-plane mechanisms. Those paths are
  evaluated using the trusted base.
- Builder/reviewer separation and provenance remain product requirements of #1054 even though the
  first policy/auto-merge slice does not yet implement the whole self-development loop.

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
  not implement code, approve its own high-risk work, or bypass the self-development policy.

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
