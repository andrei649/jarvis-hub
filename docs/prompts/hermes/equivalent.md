# Hermes ledger: adversarial audit of the `equivalent` rows (ultracode)

You are working in `andrei649/jarvis-hub` on branch `claude/cto-session-recovery-qinvkg` (draft PR #1207).

**Goal.** Every row that the ledger calls `equivalent` must be proven equivalent at HEAD. If you cannot prove it, downgrade it honestly. A lower headline is an acceptable result. An `equivalent` you cannot prove is not acceptable. In this bucket the headline can only stay the same or go down.

## 0. Sync and load context
- **Sync.** Run `git fetch origin && git checkout claude/cto-session-recovery-qinvkg && git merge --ff-only origin/claude/cto-session-recovery-qinvkg`.
- **Record your starting point.** Save these three things in your scratch directory:
  - the starting HEAD (`git rev-parse HEAD`);
  - `python3.12 scripts/hermes_status.py summary --json`, as the starting headline;
  - the output of `python3.12 scripts/check_test_manual.py`, as the baseline of flagged items. At the last snapshot it reported "2 flagged item groups", both pre-existing.
- **Load context.** Follow `CLAUDE.md` → `AGENTS.md` → `docs/AI_CONTEXT.md`: Tier 0 first, then only the bundle the task needs. You can also invoke the `jarvis-load-context` skill. Never load the raw repo. Then read these files:
  - `docs/HERMES_SPRINT.md`:
    - "Ce înseamnă terminat" (about lines 66–94) says what "complete" means;
    - "Cum se menține statusul" says how status is maintained.
  - `docs/hermes/full-parity-2026-09-27.md`
  - `docs/handoff/2026-09-28-codex-review/README.md`, including its known gaps (§ "Known gaps") and the pending AGENTS.md owner decision.
  - `scripts/hermes_status.py`. Its `assess()` function is the schema contract.
  - `tests/test_hermes_sprint_status.py`
  - Earlier per-row reviews and plans in `docs/hermes/h*-*.md` for any row you audit, e.g. `h513-code-equivalence-review.md`. They are context, and the frozen requirement text wins over them.
- **BACKLOG.md is about 1 MB.** Only query it, never load it whole. Each of these is a separate command:
  - `python3.12 scripts/backlog.py counts`
  - `python3.12 scripts/backlog.py sections`
  - `python3.12 scripts/backlog.py show HEQ-1`
  - `python3.12 scripts/backlog.py find <regex>`

  For ledger rows, use `python3.12 scripts/hermes_status.py show <ID>` or `list --state equivalent --limit 697`, and `scripts/ledger.py stats|clusters|list|show`.
- **Interpreters.**
  - `python` and `python3` may be 3.11.
  - pytest and `status_sync.py` need **python3.12**, because `agents/core/media_providers.py` uses PEP 695 syntax, which fails to parse on 3.11.
  - In this sandbox bandit is installed only for **python3.11**. Use whichever interpreter has it.

## 1. Scope and stop rules
- **Merging and pushing.**
  - Never merge and never deploy.
  - Push only to `claude/cto-session-recovery-qinvkg`, and keep PR #1207 a draft. A draft is never auto-merged (`selfdev-policy.json` `require_non_draft`).
  - This prompt authorizes pushing to that one branch and nothing else.
- **Two `AGENTS.md` sections added by Codex on 2026-09-27 in `beb2ee5a` are waiting on an owner decision** (see the handoff README):
  - the "Keep this sprint local" line (`AGENTS.md:21-22`);
  - the "Owner-approved resource plan (2026-09-27)" section.

  Do not edit them. Honour the parts of the resource plan that are still sound:
  - one writer per file;
  - subagents must not spawn their own subagents;
  - run full suites serially, at milestones only.
- **Protected paths.**
  - Never edit anything under `protected_paths` in `selfdev-policy.json`. That includes:
    - `agents/core/kernel/**`, `agents/core/security/**`, `agents/core/secrets/**`, `agents/core/secret*`;
    - `.github/workflows/**`, `.github/actions/**`;
    - `AGENTS.md`, `MAX.md`, `MOONSHOT.md`, `NERVA_VISION.md`;
    - `selfdev-policy.json` and `scripts/selfdev_policy.py`.
  - You may read and cite them.
  - If a row's defect lives in a protected path, downgrade the row honestly and record it for the owner. Security work belongs to the owner and goes last.
- **Rows you skip.** Skip any row whose proof needs network, hardware, macOS, a paid provider or an owner decision. For a skipped row:
  - leave its status unchanged;
  - do not stamp new evidence on it;
  - report it as **blocked and unverified**, never as confirmed;
  - record the reason.

  Check the existing P-items in `docs/OWNER_TASKS.md` first (P27–P31 are the Hermes-related ones). Add a new entry only if nothing there covers it.
- **Code verdict versus live proof.** A code verdict is not a live-service proof (`docs/HERMES_SPRINT.md` "Verdict de cod și probă pe serviciul real sunt lucruri distincte"). The ledger status is a code verdict:
  - Do not downgrade a row only because no live service or device run exists.
  - Never claim live proof in a summary.
- **CI you leave alone.** The `github-advanced-security` check belongs to the owner (P29). Do not try to fix it.
- **Scope decisions you never change.**
  - Never mark a row `excluded`.
  - Never write `needs_review` as a recorded status; it is only derived.
  - Never edit `scope_reopenings`.
  - Never change a ledger `decision`.
  - `docs/research/2026-09-07-hermes-absorption-ledger.json` is frozen.
- **Code changes allowed in this audit.**
  - (a) Adding tests that pin a behaviour a row claims.
  - (b) Fixing a defect you have demonstrated, with the smallest possible fix.
  - Anything bigger: downgrade the row to `partial`, name the gap in `remaining`, and leave the build to the partial-bucket session.

## 2. Compute the work live
Do not trust any list in the docs, including this prompt. Run this from the repo root:
```python
import sys, json, fnmatch; sys.path.insert(0, "scripts"); import hermes_status as hs
from pathlib import Path
ledger, data = hs.load(); rows = hs.assess(ledger, data)
recorded = {r["id"]: r["status"] for r in data["reviews"]}
base_eq  = [r["id"] for r in rows if r["status"] == "equivalent" and r["basis"] == "baseline_2026-09-07"]
stale_eq = [r["id"] for r in rows if r["basis"] == "stale_evidence" and recorded.get(r["id"]) == "equivalent"]
rev_eq   = [r["id"] for r in rows if r["status"] == "equivalent" and r["basis"] == "reviewed"]
original = lambda hid: ledger["capabilities"][int(hid[1:]) - 1]   # full frozen requirement
protected = json.loads(Path("selfdev-policy.json").read_text())["protected_paths"]
is_prot = lambda p: any(fnmatch.fnmatch(p, g) or p.startswith(g.rstrip("*")) for g in protected)
prot_rows = sorted({r["id"] for r in data["reviews"] for e in r["evidence"] if is_prot(e["path"])}
                   | {h for h in base_eq + rev_eq if "agents/core/kernel" in json.dumps(original(h)) or "agents/core/security" in json.dumps(original(h))})
```
At the last snapshot these came to `base_eq`=108, `stale_eq`=0 and `rev_eq`=82, and three equivalents cited protected files: H313, H398 and H410. Recompute the lists at start and after every merge from origin. Other sessions' code edits can make your equivalents go stale at any time.

**Order of work.**
1. **`base_eq`.** These rows were inherited from the 2026-09-07 audit. All of them are `keep` rows. They have no evidence and were never reviewed against the code. When you confirm one, write a new review entry for it. Its basis becomes `reviewed`, and the headline does not change.
2. **`stale_eq`.** These are recorded as equivalent, but their evidence files have since changed. They also count in the needs_review bucket, so check §6 first to make sure that session has not already restamped them.
3. **`rev_eq`.** Re-audit these. H513 is among them; its "Now" cell in `docs/hermes/build-queue.md` still says `partial`.

Flag every row in `prot_rows`. You may confirm such a row on read-only evidence, but any fix it needs goes to the owner.

## 3. Method (workflow orchestration)
1. **Triage: read-only fan-out.** For each row:
   - Run `show <ID>` to read the full frozen requirement: `hermes`, `nerva_evidence`, `rationale` and `governance`.
   - Find the code and tests that implement it, and run those tests under python3.12.
   - Classify the row as *provable*, *gap suspected*, *defect suspected* or *blocked (with reason)*.

   Produce a ranked plan, batched by cluster so each batch shares context.
2. **Batches of about 8–12 rows.** Each batch gets two agents: an **auditor** and an **independent skeptic**. Neither may spawn further agents.
   - The auditor drafts the review entries.
   - The skeptic is a separate agent that sees only the draft and the repo. It tries to refute each entry. It looks for:
     - a clause of the requirement that nothing covers. If a row asks for both X and Y, X alone leaves it partial.
     - a missing usable entry point (CLI, UI or API reachable by the owner), or missing authority limits. `docs/HERMES_SPRINT.md` says that a class, an adapter, a manifest, a route without a client, or a demo with fake data does not close a row on its own.
     - a `keep` verdict that rests only on the old audit's "parity"/"superior" wording.
     - a citation whose line does not say what the summary claims.
     - a test that is skipped or xfail, that mocks the behaviour away, or that does not assert the claim.
     - a stub or dead code path behind the claim.
   - If they still disagree, either downgrade the row and put the disputed item in `remaining`, or bring in a third judge.
   - The requirement text wins over earlier verdicts.
3. **Pinning tests.** If a claimed behaviour has no test, add one, preferably in a new test file.
   - Mutation-test every new test: break the cited line, confirm the test fails, then restore the line.
   - A test that survives the mutant does not count as evidence.
4. **Defects are build work.** Work one row, or one tightly coupled cluster, at a time:
   - For L/XL rows, run a judge panel on the design first.
   - Write the failing test first.
   - Make the smallest fix.
   - Run a closure verifier and an adversarial hunter.
   - Repeat fix rounds until no MAJOR or MINOR regressions remain. Record NITs and rare pre-existing issues as known gaps.
   - Mutation-test the fix.
5. **One writer per file.** Subagents write their drafts as JSON to a scratch directory. Only the coordinator edits these shared records:
   - `docs/hermes/assessment.json`
   - `BACKLOG.md`
   - `docs/hermes/build-queue.md`
   - `docs/test-manual/*`
   - `docs/OWNER_TASKS.md`

## 4. Ledger honesty
- **What `equivalent` requires.**
  - `remaining` is exactly `""`.
  - The evidence includes at least one source file: under `agents/`, `frontend/src/`, `mobile/src/` or `desktop/`, and not under `/test/`. `scripts/` and `docs/` do not count as source.
  - The evidence includes at least one test file: under `tests/`, or a path containing `/test/`.
  - The named tests exist, are collected and pass under python3.12.
  - The whole accepted requirement is covered.
- **Downgrades.** Set the status to `partial` or `missing`.
  - `remaining` must name the concrete missing items. It can never be blank or whitespace; the checker lets whitespace through, so this rule is yours to enforce.
  - `summary` says what does exist.
- **Which files to pin.** Pin the files that actually implement and test the claim. When a narrower module carries the behaviour, prefer it over a hub file. Every pin on a heavily pinned file is a future drift liability (see "Drift" below).
- **Citations.** Check every `path:line` against the actual content: print the line and confirm it supports the claim. The checker only confirms that the first cited line of a pinned file exists and is not blank. Cite pinned files anyway so the checker runs, but the content check is your job.

  A citation that does not resolve is **fatal**: every `hermes_status.py` command exits 2 with "citation does not resolve in pinned evidence". So run `check` after every edit.
- **Entry format.**
  - Write `summary` and `remaining` in the language and style of the existing entries, which is Romanian.
  - Keep the key order `{id, row_sha256, status, summary, remaining, evidence:[{path, sha256}]}`. Build each entry like this:
    ```python
    def entry(hid, status, summary, remaining, paths):
        return {"id": hid, "row_sha256": hs.digest(original(hid)), "status": status,
                "summary": summary, "remaining": remaining,
                "evidence": [{"path": p, "sha256": hs.file_digest(hs.REPO / p)} for p in paths]}
    ```
  - Keep `reviews` sorted by id, with no duplicate ids and no duplicate evidence paths.
  - Serialize with `json.dumps(d, ensure_ascii=False, indent=2) + "\n"`. That round-trips byte-for-byte.
  - Update `base_sha` to the full 40-character commit you reviewed against; never invent one.
  - Set `assessed_at` to `datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")`.
- **Never refresh a hash without re-reading the row.**
- **Drift.** Before you edit any file, list the rows that pin it:
  ```python
  [r["id"] for r in data["reviews"] if path in {e["path"] for e in r["evidence"]}]
  ```
  - Heavily pinned files demote dozens of rows when they change. Examples: `agents/cli/nerva.py`, `tests/test_nerva_cli.py`, `agents/core/orchestrator.py`, `agents/core/settings_db.py`, `agents/web.py`, `frontend/src/gap.tsx`, `agents/core/agent.py`. The last of these is invisible to grep; see `tests/test_soul_injection_guard.py:35-41`.
  - If your change drifts other rows, re-read each one in the same change, then either restamp it or downgrade it.
  - To remap a drifted row's citations, first find the version its digest actually pins:
    1. Walk `git log --format=%H -- <path>`.
    2. For each commit, write `git show <sha>:<path>` to a temp file and hash it with `hs.file_digest`.
    3. Stop at the one that matches. That version can be older than the last restamp base; this is the lesson from the 2026-09-28 recovery.
    4. Map each cited line by its content from that version to the current file.
- **Tests that pin rows.** `tests/test_hermes_sprint_status.py` pins some rows' statuses and citations:
  - H515, H598, H566, H660 and H595 must be partial;
  - H456, H477 and H510 must each keep a pinned file intact with a citation that resolves;
  - at least 50 rows must have basis `reviewed`;
  - both generated reports must be byte-equal to regenerated output.

  If an honest verdict conflicts with it, change the test and give the reason in the commit message. Never bend the verdict to fit the test.

## 5. Records in the same change
- **Ledger.**
  - `python3.12 scripts/hermes_status.py write && python3.12 scripts/hermes_status.py check`
  - `python3.12 -m pytest tests/test_hermes_sprint_status.py -q`
- **BACKLOG.** Find the section heading with `grep -n "^## Current sprint: Hermes" BACKLOG.md`. It sits at about line 15; `backlog.py sections` lists it as L1817, which is where its task rows start. Edit only inside that section:
  - Add a dated bullet at the top, in the style of the existing ones. Give the headline, rows confirmed, rows downgraded and blocked, and "Tests: backend X → Y".
  - Fix the HEQ-1 bullet (find it with `backlog.py find HEQ-1`). Its "590 accepted and 107 intentionally excluded" text is stale: all 697 rows are now accepted.
- **`docs/hermes/build-queue.md`.**
  - Add a dated "equivalent audit" entry listing rows confirmed, rows downgraded with the reason, and rows blocked.
  - Correct the "Now" column for any queue row you touch.
  - Add a plan section for each downgraded row you queue.
- **Test manual.** Add cases for new tests to the matching chapter in `docs/test-manual/`. Then run `python3.12 scripts/check_test_manual.py`. It always exits 0, so read its output and compare it with your starting baseline.
- **Status sync.**
  - Recount backend tests: `python3.12 scripts/status_sync.py --reuse-js-counts`. Drop `--reuse-js-counts` if frontend or mobile tests changed.
  - Then run `python3.12 scripts/status_sync.py --check --reuse-test-counts`.
  - Never run either one from inside pytest.
- **Gates.**
  - Lint: `ruff check .`
  - Bandit: `python3.11 -m bandit -r agents scripts -q -b .bandit-baseline.json`
  - Tests:
    - After each batch, run the targeted suites.
    - Before each push, run the full suite, serially and matching CI:
      ```
      JARVIS_TESTING=1 TMPDIR=<scratch>/tmp python3.12 -m pytest tests/ -n auto --dist loadfile --timeout=90 -q --tb=short --junitxml=<scratch>/pytest-junit.xml
      ```
      Then run `python3.12 scripts/status_sync.py --verify-test-count backend --test-result <scratch>/pytest-junit.xml`.
  - If routes change: `python3.12 scripts/gen_api_sweep.py --check`. Regenerate it by dropping `--check`, and update the route snapshots:
    - `python3.12 tests/test_route_parity_guard.py --update`
    - `python3.12 tests/test_openapi_parity_guard.py --update`
    - `tests/_snapshots/route_auth.json` has no updater; edit it by hand.
    - Use the `jarvis-add-route` skill.
  - If the frontend changes: `cd frontend && npm ci && npx tsc --noEmit && npm run typecheck:e2e && npx vitest run && npm run build`, then commit the rebuilt `agents/web/v2`. CI's `hud-v2-build` fails when that bundle is stale.

## 6. Shared branch
Other sessions push to this branch in parallel: the missing, partial and needs_review sessions.

- **Before each batch.** Fetch, then list the review ids that changed on origin since you started:
  ```python
  import json, subprocess
  rv = lambda ref: {r["id"]: r for r in json.loads(subprocess.check_output(["git", "show", f"{ref}:docs/hermes/assessment.json"]))["reviews"]}
  a, b = rv(START_HEAD), rv("origin/claude/cto-session-recovery-qinvkg")
  changed = sorted(k for k in a.keys() | b.keys() if a.get(k) != b.get(k))
  ```
  Skip rows in `changed` that you have not already finished, then recompute §2's lists.
- **Before each push.**
  - Run `git fetch origin && git merge origin/claude/cto-session-recovery-qinvkg`. Never rebase and never force-push.
  - Merge `assessment.json` by review id: load both sides (`git show :2:docs/hermes/assessment.json` and `:3:`) and keep both sides' entries. If both sides changed the same id, re-read the row and decide. `scope_reopenings` must stay byte-identical.
  - Hand-merge `BACKLOG.md`, `docs/hermes/build-queue.md` and `docs/test-manual/*` by keeping both sides' entries. Then refresh the counts in your BACKLOG bullet from the live summary.
  - Do not hand-merge generated files: `HERMES_STATUS.md`, `docs/HERMES_CAPABILITIES.md`, `STATUS.md`, `project-status.json`, `README.md`, `NERVA.md`, `GO_LIVE_PLAN.md`. Take origin's side, then regenerate them with `hermes_status.py write` and `status_sync.py`.
  - Re-run `hermes_status.py check` and the ledger test. If code merged in from other sessions drifted rows you just stamped, re-read and restamp them before you push.
- **Commits.** Commit once per batch. End each message with the attribution trailers your session's system prompt specifies.
- **After pushing.** Watch PR #1207's checks with the GitHub MCP tools, or `gh` if it is installed.
  - Read the logs of failing jobs.
  - Drive green every failure your commits caused, except `github-advanced-security`.
  - If a failure comes from another session's commits or needs a workflow edit (a protected path), record it in your report and do not fix it.

## 7. Report
- **What ran.** Give honest counts: suites run, test counts, passes and failures, and anything not run, with the reason. Never describe a suite you did not run as passing.
- **Final report.** List:
  - rows confirmed equivalent, with the evidence added;
  - rows moved from→to, each with a one-line reason;
  - rows blocked and left unverified, with the reason (protected path, owner decision, hardware or network);
  - owner decisions needed, citing the `OWNER_TASKS` references;
  - known gaps left open;
  - the new headline (`equivalent/697`) compared with the starting one, and why it moved.