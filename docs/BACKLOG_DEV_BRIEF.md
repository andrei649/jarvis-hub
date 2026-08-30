# Backlog dev brief — prompt for the implementing agent

> Companion to [`BACKLOG_DAILY_BRIEF.md`](BACKLOG_DAILY_BRIEF.md). That one *prioritises*;
> this one is handed to whoever (or whatever) actually writes the code.
> Ground truth is always [`BACKLOG.md`](../BACKLOG.md) — this brief is a snapshot taken
> against `main` at `5e6e184` (2026-08-30) and goes stale the moment work lands.

Paste everything from **PROMPT** down into the implementing agent.

---

## PROMPT

You are implementing against the `jarvis-hub` repo (product name: **Nerva**). Work through the
queue below in order. **One item = one PR.** Do not batch items.

### Before you touch anything

1. Invoke the `jarvis-load-context` skill first. The raw repo is ~2M tokens; do not read it
   whole. `docs/AI_CONTEXT.md` says what to load per task type.
2. Read `AGENTS.md` (shared assistant instructions) and `docs/ARCHITECTURE.md` (entry points,
   module index, recipes).
3. Check `BACKLOG.md` for the item's current status before starting — the snapshot below may
   already be stale.

### How your PR will be judged

CI classifies every PR by tier (`docs/adr/0001-autonomous-development-boundary.md`):

- **tier 0**, and **tier 1 that tightens or is neutral** (adds a check, narrows a permission,
  fixes a gate bug) → auto-merges on green.
- **tier 1 that loosens** (grants a write permission, removes a job, widens a boundary) → held
  for the owner. `boundary` is a required check, so it cannot merge without them.

Write tightening changes where you have the choice. If an item genuinely needs a loosening
change, isolate that part into its own small PR so the rest can flow.

### The trap you must not walk into

`main` runs an **enforcing** Nerva movement gate. Any PR touching a path in the gate's registry
must carry an exact-head attestation in its body **plus three fresh owner receipts** posted as
comments on issues 757, 778 and the implementation issue — each binding the exact head SHA,
re-done on every push. Only the owner can post them (the gate hardcodes
`login == "andrei649"` / `author_association == "OWNER"`).

Registry paths that will trip it:

```
BACKLOG.md            GO_LIVE_PLAN.md   NERVA.md   README.md   STATUS.md
project-status.json   .github/workflows/{ci,nerva-roadmap,pr-auto-merge}.yml
docs/nerva2/*         scripts/check_nerva_{issue_movement,program_manifest}.py
tests/test_nerva_{issue_movement,program_manifest}.py
tests/test_pr_auto_merge_policy.py
docs/superpowers/{plans,specs}/2026-08-07-b2-live-issue-ledger*
```

**Item 1 below fixes this.** Until it lands, keep every other PR clear of those paths. That
includes the `BACKLOG.md` refresh that `AGENTS.md` normally requires on merge — for now, note the
backlog change you *would* make in the PR body and let item 1 unblock the real sync.

If you find yourself editing the gate's own wiring or its tests to make a check go green: stop.
That is removing the assertion rather than satisfying it. Raise it with the owner instead.

### Validation every PR must pass locally before you push

```bash
python -m pytest tests/ -q                      # full backend suite
python -m ruff check <changed>                  # blocking lint gate
python -m ruff format --check <changed>
python -m bandit -r agents scripts -q -b .bandit-baseline.json   # blocking, exit 0 required
python scripts/status_sync.py --reuse-test-counts --check        # generated truth in sync
```

Never regenerate `.bandit-baseline.json` to clear a finding you introduced — fix it, or suppress
that one line with a named `# nosec BXXX` and a reason. Never skip, disable or quarantine a test.

Known environment noise in containers (not regressions — confirm against a pristine `main`
checkout before blaming your diff): `test_ssrf.py` (network sandbox), `test_sys_info_honest.py`
and `test_system_monitor.py` (no hardware sensors), `test_task_mediation_evidence.py`
(cross-process). The project floor is Python 3.12; some dev containers run 3.11. Hosted CI is the
authority.

---

## The queue

### 1. Narrow the movement-gate registry — do this first, it has a deadline

**Why now:** the enforcing gate and the auto-merge pipeline landed a day apart and collide. A
tier-0 PR touching `BACKLOG.md` can never go green (it needs three human comments), so it will
sit forever. `AGENTS.md` mandates a `BACKLOG.md` refresh after every merged PR, so this fires on
the next routine sync. No PR has hit it yet only because #979 landed before the gate and
#980/#982 happened to miss those paths.

**Do:** in `docs/nerva2/NERVA_PROGRAM_MANIFEST_V1.json`, drop these six from
`movement_gate.registry`, keeping the other thirteen:

```
BACKLOG.md  GO_LIVE_PLAN.md  NERVA.md  README.md  STATUS.md  project-status.json
```

The line to hold: **the gate governs its own machinery and CI config; it does not govern
generated status narrative.** Regenerate `NERVA_PROGRAM_MANIFEST_V1.md` from the JSON and update
`tests/test_nerva_program_manifest.py` if it pins the registry contents.

**Constraints:** `registry` is in `mutable_gate_fields`, so this needs no schema bump — but the
manifest itself is a registry path, so **this PR needs the full ceremony**. Prepare the
attestation and the three receipts and hand them to the owner to post; do not attempt to post
them yourself. Leave `enforcement_state: "required"` alone: `required → safety_disabled` is a
one-way door in the code ("safety-disabled gate cannot return without a new schema").

Widening the registry again later is a normal PR, so err toward narrow.

### 2. A1 — ⭐B0 governed-autonomy demo + `MANUAL_TESTING.md` pass

The last `⬜` on the 1.0 critical path, and **blocked on an owner decision, not on code.** The
owner was asked twice how it should read and has not answered. Do not guess a status for it.
Instruments are ready: `docs/TEST_MANUAL.md` (15 chapters), `docs/COWORK_QA_RUNBOOK.md` §3b/§3c.
Chapter 15 (`ADV`, adversarial audit + missing-feature ledger) is written but unexecuted.

**Your move:** ask the owner to either run it on the RTX box or restate A1's status. If they run
it, turn the findings into bounded slices. Otherwise skip to item 3.

### 3. B7 — Hermes v3 Phases 3/5/6 live wiring

File-RPC exec · gateway sessions · cron. Primitives are merged; the row says **on-demand only —
wire behind real pull.** Do not speculatively build this. It is also entangled with the open #906
integration authority (non-admin builder credential, distinct integrator, external store/keys).
Confirm with the owner that there is real demand before writing code.

### 4. H12.26 — Binary artifact store (visual-artifact lane wave 2)

The largest genuinely-open engineering item. Lets the user attach a bounded, validated binary
(image/audio/video/PDF/doc) and browse/stream/delete it from the Artifacts workspace, under the
same governance as the text Canvas: default-off, attributed, inspectable, purgeable.

Wave 1 (H12.18 / H18.20) deliberately shipped the **text** substrate only. The backlog row is
explicit that **every listed contract must land in the slice** — starting with MIME validation by
magic-bytes allowlist, never by extension or `Content-Type`. Read the full row in `BACKLOG.md`
before designing; do not implement from this summary.

Expect this to need several PRs. Land the storage + validation substrate first, default-off,
before any UI.

### 5. Remaining greenfield

`0.20 Vault` and `0.48 Video Production`. Both genuinely unstarted. Scope with the owner before
starting either — neither is on the 1.0 path.

---

## Explicitly not yours

- **A5** — MIT → Apache-2.0 licence flip. Three owner commands in `docs/OWNER_TASKS.md`.
- **A9** — tag `v1.0.0`. `agents.__version__` has read `1.0.0` since #974; `LICENSE` still says
  MIT and the repo has zero tags. The tag publishes a public GitHub Release, must be cut on
  `main`, and **must come after A5** or 1.0.0 ships under the wrong licence.
- **0.90–1.0 gates** (Freeze · RC · Partner · Burn-In · Owned) — owner-run release process.
- Posting movement receipts, flipping `enforcement_state`, or anything in
  `docs/OWNER_TASKS.md`.
