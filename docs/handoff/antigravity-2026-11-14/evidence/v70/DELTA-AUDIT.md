# V69 cumulative integration delta audit

Generated 2026-11-13 UTC. Read-only inspection of `/workspace/jarvis-hub`; no production/security/Windows file changes, staging, commits, checkout, rebase, publication, merge, deployment or full-suite run. The only deliverable written by this audit is this report. Goal: explain the actual delta to main, patch lineage, coherent review units and remaining integration evidence.

## Baseline and patch lineage

- Main baseline supplied by coordinator after current `ls-remote` verification: `1338833d5a344d277c43828a9d9314e10af792f1`, equal to local `origin/main`.
- Local HEAD and V69 package base: `686fcbf4f25ebfbb416b3a35dff29045163cffbd`.
- Six gateway commits sit above main, in oldest-first order: `45def81a` outbound transport gate; `63eab04a` per-user service installation/channel policy/command grammar; `1a8f46c3` gateway security review; `8cae5a22` systemd Environment dollar handling; `ff0f7870` email subject gate; `686fcbf4` silent-token and Telegram classification/CI bindings.
- Their committed delta is 53 files, +2,885/-127 lines. They are prerequisites, not part of the HEAD-relative `continuation.patch`.
- V69 `source-manifest.json` lists 438 dirty paths against HEAD. Fresh SHA256 comparisons of every current path match all manifest values, including null for eight deleted paths. The package contains exactly 438 `diff --git` headers.
- Existing `apply-verification.json` records `git apply --check`, application and byte comparison as passed on base `686fcbf4`. Inspected packager reconstructs the original tracked base bytes in a temporary tree, applies the cumulative patch and compares all resulting manifest hashes. This is credible exact-base reconstruction evidence; it is not direct application evidence against main, a full clean checkout or Windows. This audit did not rerun application.
- Therefore a fresh main checkout needs the six prerequisite commits (or a content-equivalent cumulative main-based patch) before this V69 patch. Applying successive V1…V69 cumulative packages would duplicate earlier changes. Applying this V69 package over the already-dirty current checkout would also duplicate them.

## Scope accounting

| View | Paths | Added lines | Deleted lines |
| --- | ---: | ---: | ---: |
| Committed main to HEAD | 53 | 2,885 | 127 |
| HEAD to current, tracked only | 188 | 10,693 | 1,554 |
| V69 HEAD-relative package, tracked and untracked | 438 | 50,707 | 1,554 |
| Main to current, tracked only | 212 | 13,484 | 1,587 |
| Main to current, complete path union and untracked content | 462 | 53,498 | 1,587 |

Counts are distinct views, not additive file totals: committed and dirty changes overlap. Current status is 180 tracked modifications, eight tracked deletions and 250 untracked paths; none is staged. Ordinary `git diff origin/main` omits the 250 new paths, including imported runtime modules and their tests. A tracked-only patch or PR assembly would be incomplete.

The cumulative dirty package has 40,014 added lines in new files, largely focused regression coverage, but also 42 new CLI/core modules, frontend/native/mobile additions, a venv ownership helper and generated chunks. Size alone does not establish unrelated work. The latest V69 CLI history feature is a much smaller slice embedded in this cumulative delivery.

## Existing authority and high-risk surfaces

Using the protected path patterns read from **trusted origin/main** gives these cumulative protected hits:

- `agents/core/kernel/__init__.py`: sealed `hub.update`/`hub.restart` task-receipt decisions and known-mode checks.
- `agents/core/kernel/registry.py`: registration and broker action kinds for update/restart.
- `agents/core/security/recall_taint.py`: documentation of caller-owned turn/request/process scopes and an unresolved returned-text authority question.

None of these three paths is changed in the six committed gateway commits; they are prior cumulative dirty work, not new audit edits. Do not discard them solely because this session forbids security changes: that restriction constrains new action and does not authorize deleting existing work. Conversely, do not describe a cumulative PR containing them as a security-neutral CLI change.

Other behavior requiring deliberate review includes `agents/core/hub_update_apply.py`, new `hub_restart_apply.py`, `autonomy/restart_records.py`, `restart_runtime.py`, `autonomy/{queue,worker,jobs_dispatch,irreversible}.py`, `serve.py`, channel polling credential/claim/deadline modules, extension consent/runtime/store-lock and restored-command paths, archive/backup identity checks, and `scripts/bootstrap.py` plus new `scripts/venv_ownership.py`. These are execution, persistent state, credential or host-effect boundaries even when not protected by the three policy matches above.

`recall_taint.py` currently states that `process_detailed` restores its entry context before text returns to its caller, and explicitly leaves whether downstream callers may act on that text as a separate authority question. This is a recorded design/coverage limit, not proof of an exploitable defect or an instruction to change security behavior during this audit. The V66 complete-history blocker likewise concerns a proposed future legacy archive replay: its absence of occurrence/branch/capture provenance does not block the bounded retained-history V69 feature. Keep legacy archive replay excluded.

## Generated frontend assets

The eight deleted tracked JavaScript chunks have eight new untracked hashed replacements; `agents/web/v2/index.html` points to new `index-40MgBx64.js`. This is a coherent rebuild output set, not eight unexplained lost features. A static scan of literal `assets/<name>` references in current JS/HTML/CSS found no missing target. That does not replace a frontend build or browser check.

Keep source changes, `frontend/src/api/schema.gen.ts`, the updated index, all replaced/removed chunks and relevant route/parity snapshots in a consistent delivery. Including only tracked deletions or only the new index breaks the served UI. Whether the repository's accepted PR convention includes generated assets must be preserved; do not arbitrarily drop this existing committed-assets convention or regenerate it during a read-only audit.

## Review units and minimal path

These are evidence-backed dependency/revert boundaries for planning, not instructions to remove files from the current tree or a claim that independent patches have already been extracted:

1. **Committed gateway baseline:** preserve the six commits and their tests/docs. They already form the exact prerequisite lineage of the cumulative package. Review H069/H088/H089/H057 behavior together where the commits overlap; arbitrary deletion of service or outbound-gate files invalidates their fixes.
2. **Session navigation/retained transcript and CLI history:** `agents/core/checkpoint.py`, `agents/core/routers/sessions.py`, new core transcript/transition helpers, frontend/mobile session clients and views, new CLI session helpers plus the relevant `nerva.py` hunks, schema/route/parity guards, and focused session tests. The V69 helper calls `/sessions/page`; that route and checkpoint keyset implementation are absent from main. It also imports `valid_session_id` from the earlier CLI transcript helper. A V69-only three-file copy to main is therefore not sufficient.
3. **Extension and command restoration/discovery:** acquisition, plugin manager, extension consent/runtime/event/store-lock/bindings modules, skill loader/bundles/menu and command surfaces with H079/H057/H080 regressions. Many share `commands.py`, `nerva.py`, channel adapters and orchestrator with other units; extraction requires hunk-level dependency review, not a directory glob.
4. **Channel reliability/media/delivery:** claim/deadline/credential/escalation/media modules, delivery ledger and transport adapters, receipts UI/mobile projections and H070/H081/H083/H096 tests. Preserve H069 outbound-gate prerequisites. Transport-adapter files overlap command/extension wiring.
5. **Update/restart authority and host lifecycle:** all kernel registration/seal changes, signed records, queue/admission/drain/worker integration, update/restart command/status readers, `serve.py`, boot/test snapshots and H084/H624 regressions as one authority-reviewed dependency set. Do not split the physical-effect fence from its signed receipt or admission checks.
6. **Archive/restore/bootstrap safety:** archive snapshot/identity and backup receipts with their tests; bootstrap/venv ownership/locking as a further potentially independent unit after dependency inspection. These do not become V69 CLI prerequisites merely because they share the cumulative package.

The smallest **already reconstructible** local candidate is the six-commit gateway lineage plus the full pinned V69 cumulative package. It is large but has exact-base application evidence. The smallest **feature-focused** candidate is not yet mechanically proven: first extract the session page/checkpoint prerequisite, CLI transcript validation dependency and V69 parser/handler/helper/test hunks on a fresh disposable main-based tree. Include generated schema/route evidence for any API portion. Then run those focused contracts there and inspect the resulting main diff; do not declare that extraction complete from current passing tests.

Minimal reversible local integration sequence, without changing the dirty source checkout:

1. Preserve the package and manifest, record main/head pins and compare fresh source hashes immediately before assembly.
2. In an isolated disposable copy rooted at the verified main, materialize the six gateway commits' tracked tree (or their equivalent patch), then check/apply V69 once. Do not stage, commit or publish under the current authorization.
3. Compare all 438 package paths to the manifest and check unchanged files/committed baseline separately. This catches omitted untracked helpers and build chunks.
4. Run targeted backend integration/route/snapshot tests and frontend/native/mobile checks appropriate to the final candidate. Existing dirty-tree test receipts do not substitute for testing a newly extracted candidate.
5. If a small PR is desired, extract one validated rollback unit with its prerequisites; do not mutate/remove existing cumulative work to manufacture a smaller diff. Record new exact-base application and focused test receipts for that candidate.
6. Produce a reviewable main-based diff and a precise test ledger. Publication requires a later explicit instruction; no remote action follows from this plan.

## Concrete blockers versus limits

- **Direct-to-main package application is unproven/incomplete without prerequisite lineage.** The package base is HEAD, not main. This is an assembly blocker with a clear reconstruction route, not a demonstrated Git conflict with main; coordinator reports main is the merge base/ancestor of HEAD.
- **Untracked paths must be captured.** A `git diff`-only delivery omits required runtime modules and generated assets. The V69 package already captures them, so the current package does not have this omission.
- **Minimal session-only candidate is not extracted/validated.** Main lacks `/sessions/page`; whole-file copying `nerva.py` or `sessions.py` imports unrelated cumulative work. A proposed short PR needs dependency-aware hunk assembly and fresh checks.
- **Windows conflicts remain unverified.** No Windows checkout, dirty-file list, index or local branch was available to this audit. The current Linux `deploy/windows/install-service.ps1` diff against main is comments only and belongs to committed gateway lineage; there is no HEAD-relative dirty diff in that file. This establishes neither Windows clean status nor conflict resolution. Do not overwrite, reset or apply any package on Windows without comparing its actual base and local changes.
- **Cross-platform/Mac evidence remains limited.** Packaged `MAC-RECONCILIATION-BLOCKED.md` records missing transfer bytes and HTTP403, not an approval rejection; `mac-review-not-integrated` is explicitly excluded from continuation.patch. Do not silently fold it into this candidate.
- **No full-backend/live/Windows proof.** V69 review reports common 831/831 including 50 new tests, 36,678 backend collected, and reused frontend 3,178/mobile 420 evidence. Those are recorded existing results, not new executions by this audit and not a full backend green claim. A separate test-evidence audit should identify exact source pins and material failures before a publication decision.

No production defect was established by this scope/lineage inspection. No existing changes were discarded. The primary actionable gap is proving the chosen final main-based candidate, and Windows evidence remains a separate external input.
