# NERVA — PARALLEL LANE (while PR #1207 is parked)

> Paste this whole file as the opening message of a fresh assistant session. It is a **companion**
> to [`BACKLOG_DRIVER.md`](BACKLOG_DRIVER.md), not a replacement: §2–§6 of that file (one slice =
> one PR, gates, roles, non-negotiables, cadence, stop conditions) apply verbatim. This file
> replaces only its §1 pick order, and adds a file lock.
> Owner: Andrei · Created 2026-09-27 · Measured against `origin/main` @ `4937102` and
> PR #1207 @ `beb2ee5` (base `66f94ce`).

---

You are the developer on duty for **Nerva** (repo `jarvis-hub`), working a lane that must **not
collide** with an open draft PR. You work autonomously until a stop condition fires. You do not ask
questions; you find solutions, take ownership, and report honestly.

## 0. The thing you must understand before anything else

**PR #1207 *is* the 1.1.0 milestone.** `docs/NERVA_2_ROADMAP.md` §3 marks the 1.1.0 row
`🔨 this PR`. It is a 211-commit draft on `claude/cto-session-recovery-qinvkg` touching **881 files
(+172,672 / −6,383)**, and the owner has paused it — parked, not abandoned. It will resume.

So the default pick order in `BACKLOG_DRIVER.md` §1b ("the current milestone of
`docs/NERVA_2_ROADMAP.md`") points **straight into #1207's diff**. Following it is the overlap you
exist to avoid. §1 below replaces it.

Ignition is unchanged (`BACKLOG_DRIVER.md` §0): `CLAUDE.md` → `AGENTS.md` → `MAX.md` →
`MOONSHOT.md` §5 → `docs/NERVA_2_ROADMAP.md` → `BACKLOG.md` header + only the section you touch →
`docs/MAX_RUNS.md` (last three rows) → `docs/BACKLOG_ZERO_LEDGER.md` header. Then exactly one bundle
from `.claude/skills/jarvis-load-context/SKILL.md`. Never load the raw repo. Query the backlog, never
open it whole: `scripts/backlog.py counts | open | show <ID> | find <regex>`.

Open with one line and start: `▶ lane: <slice-id> — <one-line intent>`.

## 1. Derive the lock first — every session, before picking

Do not trust the list in §2; it was measured on 2026-09-27 and #1207 moves. Re-derive it:

```sh
git fetch origin main claude/cto-session-recovery-qinvkg
BASE=$(git merge-base origin/main origin/claude/cto-session-recovery-qinvkg)
git diff --name-only "$BASE"...origin/claude/cto-session-recovery-qinvkg > /tmp/pr1207.lock
wc -l /tmp/pr1207.lock          # 881 when this file was written
```

Then, for **every** file you are about to create or edit:

```sh
grep -qxF "<path>" /tmp/pr1207.lock && echo "CONTESTED — pick something else"
```

A contested path is a hard stop on that path, not a negotiation. You do not edit #1207's branch, you
do not rebase it, you do not "helpfully" fix something inside its footprint.

## 2. The map as measured on 2026-09-27

**Free — zero files touched by #1207.** This is your territory.

| Territory | Files |
|---|---|
| `agents/core/security/` | 19 |
| `agents/core/plugins/` | 29 |
| `agents/core/workflows/` | 13 |
| `agents/core/ambient/` | 12 |
| `agents/core/extensions/` · `osint/` · `creative/` · `market/` · `persistence/` · `codeintel/` · `coach/` · `security_skills/` · `system_map/` | 28 |
| Operator stack: `browser_kernel.py`, `browser_playwright.py`, `browser_transport.py`, `desktop_control.py`, `desktop_operator.py`, `desktop_setup.py`, `host_policy.py`, `host_probe.py` | 8 |
| All 10 `tests/test_{browser,desktop,operator,host_probe}*.py` | 10 |
| `.github/` · `marketing/` · `worldview/` | all |
| `agents/core/action_auth.json` | 1 |
| Untouched routers · untouched tests | 56 of 87 · 587 of 824 |

**Contested — #1207's, hands off.**

- `agents/core/routers/` — 31 of 87, including `admin.py`, `security.py`, `sessions.py`, `skills.py`,
  `voice.py`, `ops.py`, `status.py`, `autonomy.py`, `models_llm.py`, `oauth.py`, `plugins.py`,
  `memory_kg.py`, `mcp.py`, `onboarding.py`, `multimodal.py`, `webhooks.py`, `power.py`, `actions.py`.
- `agents/core/autonomy/` 24/47 · `llm/` 23/39 · `channels/` 15/24 · `memory/` 9/29 ·
  `skills/` · `voice/` · `media_backends/` 3/3 · `cameras/` 3/14 · `mcp/` 2/7 · `ingestion/` ·
  `acquisition/` · `observability/` 4/31.
- **Single files that look safe and are not:** `agents/core/kernel/registry.py`,
  `agents/core/desktop_drivers/base.py`, `agents/core/house/presence.py`, `agents/core/sandbox.py`,
  `agents/core/scheduler_service.py`, `agents/web.py`, `serve.py`.
- `frontend/` — 131 files: `src/test/` 63, `src/panels/` 28, `src/api/` 6, plus `app.tsx`,
  `gap.tsx`, `shell.tsx`, `cockpit.tsx`, `styles.css`, `modes{,2,3}.tsx`, `data.ts`,
  `console-routes.ts` and ~25 more at `src/` root.
- `tests/` — 237 of 824, and **`tests/_snapshots/route_surface.json`**.
- Root: `BACKLOG.md`, `AGENTS.md`, `NERVA.md`, `README.md`, `STATUS.md`, `GO_LIVE_PLAN.md`,
  `CHANGELOG.md`, `SOUL.md`, `HERMES_STATUS.md`, `project-status.json`, `selfdev-policy.json`,
  `.env.example`, `.gitignore`.

Three consequences worth internalising:

1. **`kernel/registry.py` is contested**, so a *new kernel kind* is not a slice you can take.
   `credential.fill` and the `JARVIS_ACTION_KERNEL` default flip (`BACKLOG.md` L1470) are both out.
2. **`route_surface.json` is contested**, so **prefer slices that add no new route.** If a slice
   genuinely needs one, accept that the snapshot reseed will conflict and say so in the PR body.
3. **`desktop_drivers/base.py` and `house/presence.py` are contested**, so driver work must be
   *additive* — a new module beside the base class, never an edit to it — and presence-gated watch
   mode is out entirely.

## 3. Pick order — replaces `BACKLOG_DRIVER.md` §1

Strict, first match wins. A row qualifies **only if every file it needs is free** by §1.

a. **Red `main`** — a failing push-to-main run, a red nightly (`reality.yml`, `e2e.yml`,
   `eval-nightly.yml`, `soak.yml`), or a test that failed twice this week. Root-cause it. Never skip,
   quarantine or loosen a test. This outranks the lock: if the fix is inside #1207's footprint, fix
   it anyway on a minimal branch and say so in the PR body.
b. **`SEC-*` residuals** — `agents/core/security/` is entirely free. `scripts/backlog.py show SEC-B5`
   (taint by dataflow, not declared origin) and `SEC-B6` (gate hardening) are the two open rows.
c. **`DRA-*` residuals whose files are free** — `DRA-60` (independent-integrator acceptance in
   repository controls) lands in `.github/`, which is untouched.
d. **The operator lane** — `browser_*`, `desktop_*`, `host_*` and their ten tests are all free, and
   1.2.0 "Proven hands" is the next milestone. **Recount before picking:** §3's 1.2.0 row calls the
   driver rows ✅ delivered, while the wave report at `docs/NERVA_2_ROADMAP.md` ~L97–118 calls
   `op-driver-factory`, `op-macos-driver`, `op-linux-driver`, `op-windows-backend`, `op-desktop-core`,
   `op-browser-governed` and `op-benchmark` "did not land in this wave". Those two statements
   disagree; the modules and tests *are* in the tree, so grep before you believe either. Whatever is
   genuinely thin here is yours. What is *owner-hardware proof* is not a slice — packet it.
e. **Debt that blocks a–d** in free territory (tooling, stale generated docs, a flaky test in an
   untouched file).

Never picked: owner-gated rows (hardware, credentials, GitHub settings, legal, demo video, design
partners). They get a complete packet in `docs/OWNER_TASKS.md` and the row stays honest. `GAP-4`
(the Hermes head-to-head) and `DRA-62` (measured VRAM numbers) are owner rows — do not start them.

Also never picked, specifically because of this lane: anything Hermes-equivalence
(`HEQ-1`, `HERMES_STATUS.md`, `docs/hermes/`). That whole surface is #1207's subject matter.

## 4. The one overlap you cannot avoid, and how to handle it

`AGENTS.md` requires a **BACKLOG sync in the same PR** and `scripts/status_sync.py` before push.
Both write files #1207 also changed: `BACKLOG.md`, `project-status.json`, `STATUS.md`, `README.md`,
`NERVA.md`, `GO_LIVE_PLAN.md`. You cannot comply and stay out of the footprint, so:

- **Keep the BACKLOG touch surgical** — tick exactly the ids you closed, add no prose to sections
  #1207 is rewriting, and never reflow or reorder a table.
- **Never hand-merge a generated artifact.** On conflict: `git checkout --ours <file>`, then re-run
  `python scripts/status_sync.py --reuse-js-counts` and let the tool rewrite it. Hand-editing a
  counter is how a wrong number ships.
- `--reuse-js-counts` is the right invocation when Node deps are absent; the frontend count command
  exits 127 without `frontend/node_modules` and fails the whole sync.
- Say in every PR body: *"Generated artifacts will conflict with #1207; resolve by re-running
  status_sync, not by hand."* That sentence is for whoever rebases #1207.

## 5. Everything else is inherited

`BACKLOG_DRIVER.md` §2 (one slice = one PR, design inline, test-first, the full gate list), §3
(the builder never accepts its own work — R2/R3 needs an independent reviewer), §4 (the
`MOONSHOT.md` §5 non-negotiables, never streamlined), §5 (append a row to `docs/MAX_RUNS.md`), §6
(stop conditions) apply unchanged. Read them; they are short.

One addition to §6: **stop and report if the free territory runs out of AI-executable rows.** Do not
drift into #1207's footprint to stay busy. Parking a lane honestly beats two branches fighting over
`routers/admin.py`.

End with one line: `■ lane: <what shipped> — next: <slice-id> — #1207 footprint untouched: yes/no`.
