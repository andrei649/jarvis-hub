# Hermes parity: build the `missing` rows (ultracode)

You are continuing Hermes-parity work on `andrei649/jarvis-hub`. The branch is `claude/cto-session-recovery-qinvkg` and the PR is draft #1207. You have none of the earlier conversation, so everything you need is in this prompt or in the repo. Other sessions are working on the `partial`, `equivalent` and `needs_review` buckets at the same time, on the same branch.

**Your bucket** is every row whose *live* status is `missing`.
- Take each buildable row to `equivalent`. If you cannot finish it, take it to an honest `partial` that names exactly what is left.
- Record every row you cannot build, with the reason.
- Do not edit reviews of rows outside your bucket. The one exception is re-reading rows that your own commits drift (§4).

## 0. Sync and load context

1. **Inspect first.** Run `git status` and `git branch --show-current`.
   - Keep any existing changes, whether yours or another agent's. Never reset them, overwrite them, stage them or reformat them.
   - If the session's system instructions assign a development branch other than `claude/cto-session-recovery-qinvkg`, do not push anywhere. Work locally and ask the owner.
2. **Get the branch and its full history.**
   - `git fetch origin`
   - If `git rev-parse --is-shallow-repository` prints `true`, also run `git fetch --unshallow origin`. §4 needs the full history.
   - `git checkout claude/cto-session-recovery-qinvkg`
   - `git merge origin/claude/cto-session-recovery-qinvkg`
   - Never rebase and never force-push.
3. **Confirm #1207 is still a draft.** Use `gh pr view 1207 --json isDraft,headRefName` or the GitHub MCP tools.
   - If it is **not** a draft, do not push. The hourly auto-merge considers every non-draft PR. Work locally and report this to the owner.
   - Never mark it ready.
4. **Load context the cheap way.** Read `CLAUDE.md` and `AGENTS.md`, then `docs/AI_CONTEXT.md`. You can also use the `jarvis-load-context` skill.
   - Load **Tier 0 only**. Add one task bundle (Tier 2) per row when you need it.
   - Never load the raw repo, `BACKLOG.md` whole, or the ledger JSON whole.
5. **Query instead of loading.** Run these as separate commands, not pipes:
   - `python3.12 scripts/backlog.py show HEQ-1`
   - `python3.12 scripts/backlog.py sections`
   - `python3.12 scripts/backlog.py find 'REGEX' --open-only`
   - `python3.12 scripts/ledger.py stats|clusters|list|show "<name substring>"`. Note that `ledger.py show` matches by **name**, not by H-id.
6. **Read these before you start:**
   - `docs/HERMES_SPRINT.md` ("Ce înseamnă terminat" and "Cum se menține statusul").
     - A row is complete only when the whole accepted contract ships, including a usable entry point and its authority limits.
     - A class, adapter, manifest, route without a client, or demo on fake data does not close a row.
     - A partial row gets zero credit.
     - A code verdict is not a live-service proof.
     - Never refresh a hash without re-reviewing the row.
   - `docs/hermes/full-parity-2026-09-27.md`. Its "Evidence baseline" numbers are a dated snapshot. Its execution rules still apply:
     - pin the Hermes behaviour;
     - reproduce the gap;
     - make a localized change;
     - verify the user entry point;
     - a UI-only facade or an unconnected backend is not parity.
   - The "How to use it" paragraph at the top of `docs/hermes/build-queue.md`. Its queue table's "Now" column is **not** synced with the ledger, so trust `hermes_status.py`.
   - `docs/handoff/2026-09-28-codex-review/README.md`: the known gaps, what is owner-only, and "For the owner".
   - The P27–P31 sections of `docs/OWNER_TASKS.md` (`grep -n '^## P' docs/OWNER_TASKS.md`).
7. **Check the interpreters.** Run `python3 --version` and `python3.12 --version`, and use **python3.12** for all Python.
   - In the reference sandbox, `python3` is 3.11. It cannot import `agents/core/media_providers.py` (PEP 695 syntax), so pytest collection, the route guards and `status_sync.py` fail under it. CI uses 3.12.
   - For bandit, use whichever interpreter has it: `python3.12 -m bandit --version || python3.11 -m bandit --version`.

**Two `AGENTS.md` sections are waiting on an owner decision.** Codex added both in commit `beb2ee5a`. See `docs/handoff/2026-09-28-codex-review/README.md` → "For the owner".

- **`AGENTS.md:21-22`, "Keep this sprint local: no push, merge, or deployment until the owner requests publication"** (echoed in `selfdev-policy.json` → `description`).
  - The owner requests publication *to this branch only* by pasting this prompt.
  - Merge and deploy stay forbidden.
  - If the owner wants local-only work, they delete this paragraph. You then commit locally and never push.
- **`AGENTS.md:124-145`, "Owner-approved resource plan".** It names Codex models, which do not apply to you. Until the owner decides, follow its model-independent rules:
  - at most **two concurrent writing agents**, each owning a disjoint set of files (one writer per file);
  - a short, self-contained brief for each agent, with its owned files, acceptance tests and dependencies;
  - subagents do not delegate further;
  - expensive full suites run serially, at milestones.
  - Read-only fan-outs for triage and verification are fine.

## 1. Compute the bucket live

Do not trust any count or list in this prompt, because the branch moves. Use these commands:

```bash
python3.12 scripts/hermes_status.py summary          # record this headline as "before"
python3.12 scripts/hermes_status.py list --state missing --limit 697
python3.12 scripts/hermes_status.py show H<NNN>      # assessment + the full frozen ledger row
```

For the triage table, run this from the repo root:

```python
import re, sys; sys.path.insert(0, "scripts"); import hermes_status as hs
ledger, data = hs.load(); rows = hs.assess(ledger, data)
caps = ledger["capabilities"]; orig = lambda hid: caps[int(hid[1:]) - 1]
status = {r["id"]: r["status"] for r in rows}
peers = {}
for i, c in enumerate(caps):
    peers.setdefault(c["cluster"], []).append(f"H{i + 1:03}")
stale_before = sorted(r["id"] for r in rows if r["basis"] == "stale_evidence")  # save this list
for r in rows:
    if r["status"] != "missing":
        continue
    o = orig(r["id"]); p = peers[o["cluster"]]
    hints = [p[int(n) - 1] for n in re.findall(r"\brows? (\d+)", o["depends_on"]) if int(n) <= len(p)]
    print(r["id"], r["basis"], o["effort"], r["cluster"], "|", o["depends_on"],
          "| hint:", [(h, status[h]) for h in hints])
```

- **`depends_on` is free text.** Examples: "nothing", "the unified `nerva` CLI", "Row: native app chrome", "the chat slash-command plane (row 1)".
  - A "(row N)" is a 1-based position inside the **same cluster** in ledger order. It is only a hint, and it can be off by one: H070's "outbound safety … (row 12)" is really H069, not H068.
  - Resolve every dependency **by name**, e.g. `python3.12 scripts/hermes_status.py list --cluster <cluster> --limit 697 | grep -i '<words>'`.
  - Then check the code. A dependency blocks only if the part this row needs is actually absent.
- When this prompt was written there were about 64 such rows.
  - All but H545 were inherited from the 2026-09-07 baseline and never reviewed against code.
  - H545 has a review whose `remaining` lists its parts and its dependency on H542, which is also missing.
  - Most rows are M effort, and most name dependencies.
  - The 2026-09-07 verdict can be wrong in either direction.
- A row that shows as `needs_review` belongs to another bucket, even if its recorded status is `missing` (for example H468). Leave it alone unless your change drifts its evidence (§4).
- Save `stale_before`. Rows that were stale before your work belong to the `needs_review` session.

## 2. Scope and stop rules

**Merging, deploying and pushing**
- Never merge, deploy or enable auto-merge.
- Never mark #1207 ready.
- Push only to `claude/cto-session-recovery-qinvkg`, and only under §0's authorization.

**Protected paths.** Never edit any path in `selfdev-policy.json` → `protected_paths`:
- `agents/core/kernel/**`, `agents/core/security/**`, `agents/core/secrets/**`, `agents/core/secret*`;
- `selfdev-policy.json`, `scripts/selfdev_policy.py`;
- `.github/workflows/**`, `.github/actions/**`, `.github/CODEOWNERS`;
- `AGENTS.md`, `MAX.md`, `MOONSHOT.md`, `NERVA_VISION.md`, `LICENSE`, `TRADEMARKS.md`, `docs/legal/**`.

Local edits to these would be allowed, but they make the PR `control_plane` and are left to the owner.
- Some rows need a change on a protected path, such as a new action family in `kernel/registry.py` or a secret-broker fix. Record those rows as `protected` for the owner and do not build around them.
- Security work goes last and belongs to the owner.
- Never route a privileged effect around the Action Kernel. Use only its existing public API.

**Governance and product guardrails** (`MOONSHOT.md` §5, `AGENTS.md` conventions)
- The row's ledger `governance` text is part of its contract. Each effect must land at the stated tier through the kernel.
- Money, locks and security actions never rise above the approval queue.
- New skills and integrations follow the sandbox → verification → approval → registry path.
- Stay local-first. Every cloud hop is opt-in, default-off and auditable.
- `frigga`, `ultron` and `howard` stay `LOCAL_ONLY_AGENTS` and never get a cloud fallback.
- Keep the default-off product posture.

**Skip, and record why, when the accepted contract cannot be built and tested in this environment.** That means rows that need:
- a real remote account or service to exercise at all;
- real hardware, macOS, or signed installers (owner certificates);
- a paid provider;
- a toolchain you do not have, such as a Tauri/Rust build with a display;
- an owner decision.

Rows whose integration can be tested offline, with local fakes or loopback, **are** buildable. Say in the review that no live-service proof was run.
- For an owner decision, add an entry to `docs/OWNER_TASKS.md` under the next free `P` number, found with `grep -n '^## P'`. Follow the P27–P31 format.

**Dependencies**
- Do not add third-party Python or npm dependencies. They change the hash-pinned locks behind the `in-sync` and `pip-audit` checks, and installing them needs network access. If a row truly needs one, record it for the owner.

**Upstream Hermes**
- `docs/hermes/upstream-reference-2026-09-27.json` is a manifest. It holds the pinned upstream commit `59b2aeef…`, the inspected source paths and digests, and superseded metrics. It does not describe behaviour.
- The behaviour you must match is the ledger row's `hermes` field.
- If you need upstream source, read NousResearch/hermes-agent at that commit, read-only.
  - Never install or run it, and never import profiles or secrets.
  - Keep attribution and license notices on anything you copy.

**CI and the ledger**
- The `github-advanced-security` check (P29) belongs to the owner. Do not try to fix it.
- Never touch these:
  - never mark a row `excluded`;
  - never add or remove a `scope_reopenings` entry;
  - never change a `skip` decision;
  - never edit the frozen ledger `docs/research/2026-09-07-hermes-absorption-ledger.json`.
- `tests/test_hermes_sprint_status.py` pins some rows' statuses (H515, H598, H566, H660, H595 must stay partial). Change a pin only with evidence.

## 3. Method: orchestrate with workflows

Work on one row, or one tightly coupled cluster, at a time. Load the `workflow-authoring` skill before you write workflow scripts.

**A. Triage (read-only fan-out).** Run one agent per row, or per small cluster.

Each agent reads:
- `hermes_status.py show <ID>`. The frozen requirement is the ledger row's `name`, `hermes`, `rationale` and `governance`. `docs/HERMES_CAPABILITIES.md#hNNN` shows only the current status line, not the requirement.
- `depends_on`, resolved by name as in §1;
- any `docs/hermes/h<NNN>-*.md` plan, plus build-queue critic notes that mention the row;
- the current code.

Each agent returns JSON with these fields:
- `id`;
- the numbered accepted parts;
- what already exists, as content-verified `path:line` (read each line);
- `depends_on` resolved to row ids, each with its live status and whether the needed part exists;
- `blocker`: one of none, protected, owner, network, hardware, toolchain or dependency, plus the reason;
- an honest estimate;
- a slice plan;
- the hot files the slice would touch.

**B. Ranked plan.**
- **Order:** dependencies first.
  - If a dependency is itself in your bucket, build it first.
  - If the needed part belongs to a row in another bucket, do not build that row. Check `origin` for in-flight work (`git log origin/claude/cto-session-recovery-qinvkg --grep H<NNN>`), and otherwise record `blocker: dependency`.
  - Among rows that are ready, take the smallest honest estimate first.
- **Where to write it:** a new section in `docs/hermes/build-queue.md` titled `## Missing rows (live, <date>, head <sha>)`.
  - Give it the freshness fields that `AGENTS.md` requires: goal, base SHA, head SHA, changed paths, next action, generation time.
  - It holds a table with the columns Row, Name, Effort, Depends on → live status, Blocker, Plan.
  - Short per-row plans follow the table. Each gives the goal, non-goals, likely paths, tests, rollback and dependencies.
- **Blocked rows** go in the table with their reason. They do not enter the build loop.
- **L and XL rows get a design judge panel.**
  - Produce at least 3 independent designs.
  - Judges score each one on the frozen requirement, fit with the Action Kernel and governance, local-first, and how testable it is.
  - Put the winning design inline in the plan or in `docs/hermes/h<NNN>-*-plan.md`.
- **Slices.** You may split a row into slices. A slice can move a row from missing to partial. The row reaches equivalent only when every accepted part has shipped.

**C. Build each row.**
1. **Red first.** Write tests that encode each accepted part (use the `jarvis-write-test` skill). Show them failing on the current head.
2. **Build.** Make the smallest change that turns them green.
   - Use `jarvis-add-route` and `jarvis-add-plugin` where they apply.
   - New routes go in `agents/core/routers/<domain>.py`. Never add inline `@app.*` routes.
   - Prefer extending an already-mounted router. Mounting a new one edits `agents/web.py`.
   - Prefer new modules over the hot files: `agents/cli/nerva.py`, `agents/core/orchestrator.py`, `agents/core/agent_runtime.py`, `settings_db.py`, `agents/web.py`, `frontend/src/gap.tsx`.
   - Before you edit any file, count the reviews that pin it, and budget for re-reading them (§4):
     ```python
     import json; d = json.load(open("docs/hermes/assessment.json", encoding="utf-8"))
     print(sorted(r["id"] for r in d["reviews"] if any(e["path"] == "agents/web.py" for e in r["evidence"])))
     ```
3. **Verify.** Run two agents in parallel, both independent of the builder:
   - a **closure verifier**, which checks on the code and in the tests that each accepted part and the governance tier hold, and that a real entry point exists;
   - an **adversarial hunter**, which looks for regressions, bypasses, races, governance holes, taint leaks and Windows/CRLF issues.
4. **Fix rounds.** Work red first, and keep going until no MAJOR or MINOR finding remains.
   - NITs and rare pre-existing issues become documented known gaps.
   - Write them into the row's `remaining` text (which forces `partial`) or into the build-queue section. Never drop one silently.
5. **Mutation-test the new code.** `mutmut` is not installed.
   - Run a workflow that applies targeted mutants to every new condition, branch and constant.
   - Run the row's tests against each mutant, restore the file after each one, and record which were killed and which survived.
   - Every survivor gets either a test or a written reason. Report the kill rate.

## 4. Ledger honesty

**Status changes only through an evidence-backed review.** Each review in `docs/hermes/assessment.json` looks like this:
```
{id, row_sha256: hs.digest(orig(id)), status, summary, remaining,
 evidence: [{path, sha256: hs.file_digest(Path(path))}]}
```
- Use exactly these keys and keep the reviews sorted by id.
- Evidence paths are repo-relative, use forward slashes and contain no `..`. There are no duplicates.
- Write the file with `json.dumps(d, ensure_ascii=False, indent=2) + "\n"`.
- Set `base_sha` to the full 40-hex commit you reviewed against, and `assessed_at` to the UTC time of the review (`YYYY-MM-DDTHH:MM:SSZ`).

**Equivalent** requires all of the following:
- `remaining == ""`;
- at least one pinned source file under `agents/`, `frontend/src/`, `mobile/src/` or `desktop/`, with no `/test/` in its path;
- at least one pinned test file (`tests/…`);
- every accepted part shipped, including the entry point and the governance tier.

Otherwise, use **partial**, and make `remaining` name exactly what is left. Never leave it whitespace-only; the checker would accept that, but it is dishonest. Use **missing** only if no part of the contract exists.

**Citations**
- Content-verify every `path:line` citation by reading the line. The checker only confirms that the first cited line of a pinned file is in range and not blank.
- A pinned-file citation that does not resolve is **fatal**: every `hermes_status.py` command then fails with exit 2.

**Stale rows.** When your change drifts pinned evidence, the affected rows show `basis == "stale_evidence"`.
- Rows in `stale_before`, and rows drifted only by other sessions' commits, are not yours.
- A row is yours if a drifted file is one your commits changed (`git diff --name-only origin/claude/cto-session-recovery-qinvkg HEAD`).
- Re-read each of your rows against the new code, then either restamp it or downgrade it honestly. Keep `row_sha256`, update the evidence hashes, and re-verify every claim and citation in `summary` and `remaining`.
- Map every old citation by content from the file version that the pinned digest actually matches. That version may be *older* than the last restamp base, which was the lesson of the 2026-09-28 recovery.
- Find the version with this script:
  ```bash
  python3.12 - "<path>" "<pinned sha256>" <<'EOF'
  import hashlib, subprocess, sys
  path, want = sys.argv[1], sys.argv[2]
  shas = subprocess.run(["git", "log", "--all", "--format=%H", "--", path],
                        capture_output=True, text=True, check=True).stdout.split()
  for sha in shas:
      blob = subprocess.run(["git", "show", f"{sha}:{path}"], capture_output=True)
      if blob.returncode:
          continue
      text = blob.stdout.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n")
      if hashlib.sha256(text.encode("utf-8")).hexdigest() == want:
          print(sha)
          break
  else:
      print("no committed version matches")
  EOF
  ```
- Never restamp a hash without re-reading the row.

## 5. Records (same commit as the code)

- **Hermes reports:** `python3.12 scripts/hermes_status.py write && python3.12 scripts/hermes_status.py check`. Never hand-edit `HERMES_STATUS.md` or `docs/HERMES_CAPABILITIES.md`.
- **BACKLOG:** the Hermes section is `## Current sprint: Hermes capability equivalence — 2026-09-09`, with HEQ-1 in it. Add a dated bullet at the top of that section, newest first, as the existing `- 2026-09-28 …` bullets are. Include:
  - what shipped;
  - tests added;
  - the mutation result;
  - the headline before → after;
  - the backend test count (`tests.backend` in `project-status.json` after `status_sync`).

  If you touch HEQ-1, fix its outdated scope text: "590 accepted and 107 intentionally excluded" should now say that all 697 rows are accepted.
- **Build queue:** update your section. Closed rows collapse to a one-line stub.
- **Test manual:** add cases to the right `docs/test-manual/NN-*.md` chapter, then run `python3.12 scripts/check_test_manual.py`.
  - It is report-only and always exits 0, so read the output.
  - The baseline is "2 flagged item groups" (in `06-standalone-pages.md` and `08-security-privacy.md`). Add no new ones.
- **Flags:** add new flags to `docs/FLAGS.md`.
- **Endpoint and HUD parity** (`AGENTS.md`), for any user-facing endpoint or HUD change:
  - update `mobile/PARITY.md`, or record the mobile gap;
  - wire the HUD V2 surface, or update `docs/design/HUD_V2_REMAINING.md`.
- **Routes:**
  - `python3.12 tests/test_route_parity_guard.py --update`
  - `python3.12 tests/test_openapi_parity_guard.py --update`
  - edit `tests/_snapshots/route_auth.json` by hand, along with `INTENTIONALLY_OPEN` / `PENDING_GUARD` in `tests/test_route_auth_matrix.py`;
  - `python3.12 scripts/gen_api_sweep.py`
  - If you can start the API server on `127.0.0.1:8765`, also run `cd frontend && npm run typegen:openapi`. The post-merge `openapi-types` job checks `src/api/schema.gen.ts`. If you cannot run it, record that.
- **Other snapshots** (`action_auth`, `capability_readiness`, `interface_contracts`, `subagent_shapes`, `tool_profiles`): regenerate a snapshot only for an intended change, using the updater that its test's failure message names, and review the diff.
- **Generated status:**
  - backend-only changes: `python3.12 scripts/status_sync.py --reuse-js-counts`;
  - if frontend or mobile tests changed: plain `python3.12 scripts/status_sync.py`, with `node_modules` installed;
  - then `python3.12 scripts/status_sync.py --check --reuse-test-counts`.

## 6. Gates (before every push)

```bash
ruff check .
python3.12 -m bandit -r agents scripts -q -b .bandit-baseline.json   # or python3.11, whichever has bandit
S=<your scratchpad>; mkdir -p "$S/home" "$S/tmp"
JARVIS_TESTING=1 JARVIS_HOME="$S/home" TMPDIR="$S/tmp" python3.12 -m pytest tests/ -n auto --dist loadfile --timeout=90 -q --tb=short --junitxml="$S/junit.xml"
python3.12 scripts/status_sync.py --verify-test-count backend --test-result "$S/junit.xml"
python3.12 -m pytest tests/test_hermes_sprint_status.py -q
python3.12 scripts/hermes_status.py check
python3.12 scripts/gen_api_sweep.py --check
python3.12 scripts/status_sync.py --check --reuse-test-counts
git diff --name-only origin/claude/cto-session-recovery-qinvkg HEAD | python3.12 scripts/selfdev_policy.py classify --stdin   # protected_hits must be []
# if frontend/ was touched:
cd frontend && npm ci && npx tsc --noEmit && npm run typecheck:e2e && npx vitest run && npm run build
```

- If the frontend build changes `agents/web/v2`, commit that output. CI fails when it differs.
- If `semgrep` or `gitleaks` is installed, also run them the way `.github/workflows/security.yml` does. Otherwise CI covers them.
- Run targeted tests while you work on a row. Run the full suites serially at each push.

## 7. Shared-branch coordination

Other sessions push to this branch too. A draft PR is not a file lock.

**Before each push:**
- Run `git fetch origin && git merge origin/claude/cto-session-recovery-qinvkg`.
- Handle conflicts:
  - **Generated files** (`HERMES_STATUS.md`, `docs/HERMES_CAPABILITIES.md`, `STATUS.md`, `README.md`, `NERVA.md`, `GO_LIVE_PLAN.md`, `project-status.json`, `docs/test-manual/14-api-surface-sweep.md`, `tests/_snapshots/*`): take either side, then regenerate them with `hermes_status.py write`, `status_sync.py`, `gen_api_sweep.py` and the snapshot updaters.
  - **`assessment.json`:** merge it review by review, keep reviews sorted, and set the newest truthful `base_sha` and `assessed_at`.
  - **`BACKLOG.md` and `build-queue.md`:** keep both sides' entries.
- Re-check that #1207 is still a draft.
- Re-run the gates and re-check for newly stale rows, because the other sessions' code may have drifted your pins, or yours may have drifted theirs.

**Commits:**
- End every commit message with the attribution trailers that your session's system prompt specifies.

**After pushing:**
- Watch CI on #1207 and drive it green: fix failures, never skip them.
- The one exception is `github-advanced-security`, which is the owner's (P29).
- Append what you ran and its results to the PR description's "How verified" section. Keep the other sessions' text.

## 8. Final report

Be honest in the report. Never call a suite passing unless you ran it. Include:
- what actually ran: suites, counts and pass/fail;
- rows moved (`Hxxx missing → equivalent|partial`) with their commits;
- rows you triaged but did not build, and why;
- rows blocked (protected, owner, network, hardware, toolchain or dependency), each with its reason and its `OWNER_TASKS` reference;
- owner decisions needed, including whether the owner still wants the two Codex `AGENTS.md` sections;
- known gaps recorded;
- mutation kill rates;
- stale rows you restamped or downgraded;
- the headline from `hermes_status.py summary`, before → after.