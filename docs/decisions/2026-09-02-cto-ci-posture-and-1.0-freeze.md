# Decision — CI posture re-gate and the 1.0 definition of done / freeze

> **Status: DECIDED (CTO, 2026-09-02) — the owner ratifies by merging the PR that carries this file.**
> Seven decisions (D1–D7) taken on the verified facts below; one row each in the
> [`docs/HISTORY.md`](../HISTORY.md) Decision Log. The 2026-08-29 owner de-gate (#981) stays the
> posture; this document bounds a small, deterministic re-gate on the PR path and writes down, once,
> what "1.0 is done" means so no surface has to re-derive it. Companion surfaces updated in the same
> PR: `BACKLOG.md` (Lane A, DRA ledger, H19 headers, version line), `GO_LIVE_PLAN.md` ("1.0 definition
> of done / freeze"), `MOONSHOT.md` §4, `docs/OWNER_TASKS.md`, `docs/AGENT_WORKFLOW.md`, `AGENTS.md`.

## The facts these decisions rest on (verified on `main` @ `268793a4`, 2026-09-02)

- **CI.** A PR runs one lane (`ruff` + `pytest` on Ubuntu, 129–228 s over the last 30 PR runs);
  the Windows matrix, sandbox containment, Signal Layer smoke, HUD suites and OpenAPI typegen drift
  run post-merge on push to `main`. Nothing blocks a merge: `pr-auto-merge.yml` squash-merges any
  non-draft PR whose `mergeStateStatus` is CLEAN, hourly, and performs no review or check of its own.
- **Red main.** Of the last 15 `main` pushes: 7 green, **4 red, 4 cancelled**. The four reds are
  **2 stale HUD bundles** (`hud-v2-build`, deterministic — a PR-path run of that step would have
  caught both) and **2 flaky Windows reds** (`tests/test_notes_store.py::
  test_list_docs_returns_docs_most_recently_updated_first`; `datetime.now()` ties at ~15 ms
  resolution broken by a random UUID — a pre-merge Windows lane catches it only ~50 % of the time).
  The four cancelled runs were superseded by newer pushes (`cancel-in-progress: true`) and never
  verified.
- **Review.** **14 of 14** human PRs merged this week (#990–#1000, #1007, #1009, #1010) have zero
  review submissions; the PR template's reviewer field was removed by #981. `docs/AGENT_WORKFLOW.md`
  still listed "independent review" (R2) and "separated roles" (R3) as required posture.
- **Counters.** Live backend test count **7,255**; tracked `project-status.json` says 7,244 (11 tests
  from #1010 never regenerated). No workflow runs `status_sync.py --check`; the in-suite release gate
  runs it with `--reuse-test-counts`, which is blind to test-count drift by design (#988 was an
  80-test drift). The H19 header read 33/33 ✅ over a 35-row table (2 ✅ + 33 🔨); the status
  artifact reported 46 open/blocked of which 33 were those 🔨 rows; A4 read as closed because of a
  ✅ inside its explanatory prose; the DRA ledger said 53 ticked + 8 open of 62 (54 + 8 is right).
- **Release.** `__version__` is 1.0.0 on `main` since 2026-08-28; CHANGELOG has a cut `[1.0.0]`
  section with a new `[Unreleased]` entry (#981) above it; no `v1.0.0` tag exists locally or on
  origin; `release.yml` (tag-triggered, version check + `build_release.sh` + GitHub Release with
  SBOM/checksums) has **never run on GitHub**, though every non-publishing step reproduces locally.
  A5 prep is landed (TRADEMARKS.md, staged Apache text, CONTRIBUTING relicense grant); LICENSE is
  still MIT. Owner directive 2026-08-28, confirmed 2026-09-01 (#1009): the tag is the A5 licence flip
  then `git tag v1.0.0 && git push origin v1.0.0` on `main`; the A1 §0 run is post-tag proof. Four
  surfaces still carried the July "expanded gate" wording.
- **Dependencies (offline `npm audit --omit=dev` / `pip-audit`, 2026-09-02).** frontend **0**;
  root `package-lock` (HUD-test tree) **5** (2 high); worldview **3 high**; worldview/mcp **5**
  (2 high); mobile **21–22** (10–11 high, device-gated Expo chain); Python `requirements.lock`
  clean. GitHub's own Dependabot count is not readable from here — the last UI reading is the
  2026-08-28 handoff (35 / 22 high); the owner reads it from the Security tab or
  `gh api repos/andrei649/jarvis-hub/dependabot/alerts?state=open`.

## D1 — CI posture: partial re-gate, bounded to ~+3 minutes on the PR path

The 2026-08-29 de-gate stays. On the PR path we add only what is deterministic and cheap:

1. **(a)** the `hud-v2-build` committed-bundle staleness check runs on pull requests too;
2. **(b)** the two cheap lanes from the #986 restore archive come back on PRs — group A
   **security-scans** (`Secret scan (gitleaks)`, `SAST (semgrep)`, `Dependency audit (pip-audit)`,
   `SAST (bandit — blocking gate)`, ~1–1.5 min) and group E **lockfile-drift** (`in-sync`, ~15 s);
3. **(c)** push-to-`main` runs are no longer cancelled by newer pushes (`cancel-in-progress` is
   false for `push`, still true for `pull_request`);
4. **(d)** the Windows matrix stays post-merge — its catch is probabilistic; the flaky test is fixed
   instead (D2);
5. **(e)** after the PR pytest run, the executed backend test count is compared with
   `project-status.json` `tests.backend` (`status_sync.py --verify-test-count backend
   --test-result pytest-junit.xml`) and drift fails the job.

**Not enforced until the owner acts.** Branch protection is an owner setting: these checks block a
merge only once they are listed as required (owner item under A4 in `docs/OWNER_TASKS.md`); until
then they are advisory and the hourly auto-merge sweep keeps merging CLEAN PRs unreviewed.

## D2 — Strictly-monotonic `_now()` in `agents/core/notes_store.py`

Only the `docs.updated_at` writers (`create_doc`, `add_block`, `update`, `move`, `delete_block`) are
in the tie class; block `ordering` keys are unique fractional keys and are not touched. Regression
test forces identical wall-clock reads. A `rowid` tiebreak would not fix the failing test.

## D3 — Scheduled Reality Harness crash

`AttributeError: module agents.core.skills has no attribute discover` at
`agents/core/observability/reality_evidence.py:162` (introduced by #980), red four nights running.
Fixed, with a test that exercises the evidence recorder's skills-discovery path.

## D4 — Ledger truth

- **(a)** `scripts/status_sync.py` gets a third horizon state: 🔨 = *delivered, runtime proof
  pending* — neither done nor open; roll-up and snippets show done / delivered-pending / open.
- **(b)** `open_release_gates()` and the horizon row classifier read the status cell's **leading**
  marker; a ✅ inside explanatory prose never closes anything.
- **(c)** BACKLOG corrections: H19 headers → 35 rows (2 ✅ + 33 🔨); DRA ledger 54 ticked / 8 open
  of 62; the stale DRA-08 "Phase 5 deliberately not built" paragraph struck (Phase 5 landed in
  #1000; Phase 6 stays open); SEC-B5 rescoped — its recall→action leg shipped in #983 (DRA-02,
  `agents/core/security/recall_taint.py`, `orchestrator.py` → `mark_turn_recall_tainted`), only
  the explicit bind/reset hardening around the HTTP recall route remains; A3 and OWNER_TASKS carry
  the 2026-09-02 offline measurements above, with GitHub's own count still an owner read; A4 leads
  with ⬜ and lists the four PR checks to mark required.

## D5 — Release truth: the 1.0 definition of done / freeze

Reconciling every surface with the owner's 2026-08-28 directive (recorded 2026-09-01):

- **`main` is feature-frozen for 1.0 from the merge of this PR.** Between that merge and the tag
  only three kinds of change land: **(1)** red-`main` fixes, **(2)** the dependency audit wave (D7),
  **(3)** the A5 relicense PR.
- **The tag is cut immediately after A5 merges:** `git tag v1.0.0 && git push origin v1.0.0` on
  `main`. **Before tagging** the owner folds CHANGELOG `[Unreleased]` into `[1.0.0]` and sets its
  date. `release.yml` has never run on GitHub; a `workflow_dispatch` `dry_run` is being triggered
  today (2026-09-02) by the coordinator as its first end-to-end check — read its result first.
- **The A1 §0 run proves the tagged build; its findings are 1.0.1.**
- **Everything else is 1.x:** the 8 open DRA rows (DRA-08 Phase 6, 27, 29, 45, 58, 59, 60, 62),
  SEC-B4's `browser_run` egress-boundary capability residual, H23.30 public demo, GAP-0
  (distribution), the ORIZONT 27–33 capability program and the H19 🔨 scale proofs.
- Surfaces reconciled: BACKLOG version line + roadmap row + Lane A (A4, A9) + the July
  "expanded gate" paragraph (kept as history, marked superseded); GO_LIVE_PLAN header, launch
  checklist and roadmap summary (+ the new section); MOONSHOT §4 "→ 1.0" row; OWNER_TASKS header,
  A8 (cleared 2026-08-28, no longer blocking), A9 (CHANGELOG fold + dry_run check).

## D6 — Review governance

The de-gated posture stays; the docs stop contradicting it. `docs/AGENT_WORKFLOW.md` R2/R3 rows and
`AGENTS.md` say independent review is *recommended*; R3 runtime/security changes get a **recorded
post-merge attestation in `BACKLOG.md`** — a reviewer distinct from the builder, bound to the merged
SHA, ending in PASS/HOLD (the SEC-B4 / SEC-B6 / #911 model from #1009). Both note that
`pr-auto-merge.yml` merges any non-draft CLEAN PR hourly with no review, and that the re-gated PR
checks block only once the owner lists them as required.

## D7 — Dependency audit wave (engineering, now)

`npm audit fix` in `worldview/`, `worldview/mcp/` and the repo-root HUD-test tree, each followed by
that tree's own tests/build. `frontend/` (already 0) and `mobile/` (the owner's device-gated Expo
tail) are not touched.

## What the owner does

1. Merge this PR (ratifies D1–D7).
2. Mark the four PR checks required in branch protection and remove the stale names (A4).
3. Land the A5 relicense PR; fold CHANGELOG `[Unreleased]` → `[1.0.0]`; check the `release.yml`
   dry run; `git tag v1.0.0 && git push origin v1.0.0` on `main` (A9).
4. Run the A1 §0 proof on the tagged build; file its findings as 1.0.1.
5. Read the real Dependabot count (Security tab / `gh api …`), dismiss stale alerts, schedule the
   mobile Expo SDK upgrade on a device (A3).
