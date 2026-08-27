# Integration Closure Sprint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reconcile overlapping delivery work and prepare only exact-head, independently reviewable PRs without pushing or merging unapproved changes.

**Architecture:** A serial ownership gate resolves overlap with open PR #945 before any competing event-loop branch is prepared. Independent R0/R2 slices then move through separate review and evidence paths; R3 security work stays held behind distinct reviewer and integrator gates. Every candidate remains an independently revertible branch and PR.

**Tech Stack:** Git worktrees, GitHub CLI, Python pytest, Vitest, TypeScript, Vite, Docker Compose, FastAPI, httpx.

---

## Operating Constraints

- Base SHA for all current local delivery branches: `75e928114024869bae75ee77937974af9dda5db3`.
- All branches are local and unpushed. Do not push, create PRs, merge, rebase, or alter remote state
  without explicit owner authorization.
- Lease state is `none` for every path.
- `BACKLOG.md` is a shared serialization point. Update it only in the selected PR after ownership is
  resolved, never from competing local branches.
- R3 requires separate builder, reviewer, and integrator. The integrator owns the merge decision.
- Exact-head evidence becomes stale after any commit.

## Branch Inventory

| Branch | Head | Intended disposition |
| --- | --- | --- |
| `wave/blocking-browser` | `8b5d358f` | Compare with PR #945; do not independently push before ownership decision. |
| `wave/blocking-codeintel` | `0981daeb` | Candidate standalone R2 PR. |
| `wave/blocking-house-onvif` | `1329eb72` | Compare with PR #945; do not independently push before ownership decision. |
| `wave/blocking-memorykg` | `b5ba406b` | Compare with PR #945; do not independently push before ownership decision. |
| `wave/gap-docs-honesty` | `adf6ba09` | Combine with flag documentation as one R0 docs PR. |
| `wave/qa4-ungoverned-counter` | `8fd144ea` | Hold for R3 independent review and integrator handoff. |
| `wave/f14-container-hardening` | `17fda1de` | Candidate draft R2 PR after runtime smoke. |
| `wave/gap6-flag-costs` | `7d8d9a09` | Combine with vision documentation as one R0 docs PR. |
| `wave/house-actuator-enqueue` | `949984cb` | Compare with PR #945; do not independently push before ownership decision. |
| `wave/ssrf-pinning-nav` | `8c06f471` | Split browser DNS offload from held R3 preflight-only pinning after exact review. |
| `fix/admin-observe-seeded-corpora` | uncommitted | Freshly verify, decide generated-bundle policy, then commit as one R2 HUD PR. |

### Task 1: Resolve PR #945 Ownership Before Any Event-Loop Push

**Files:**
- Inspect: Open PR #945 (`fix/event-loop-blocking-io`).
- Compare: `agents/core/routers/browser.py`
- Compare: `agents/core/cameras/onvif.py`
- Compare: `agents/core/routers/memory_kg.py`
- Compare: `agents/core/house/actuation.py`
- Compare: `tests/test_request_path_blocking_io.py`
- Do not modify: `BACKLOG.md` until an owner decision is approved.

- [ ] **Step 1: Capture the remote PR state and its exact changed paths**

Run:

```powershell
gh pr view 945 --json headRefName,headRefOid,mergeStateStatus,reviewDecision,statusCheckRollup,files,url
gh pr checks 945
```

Expected: record the exact remote head, failing checks, and the six changed paths before comparing
local branches. The known overlap is browser routing, ONVIF, memory KG, and house actuation.

- [ ] **Step 2: Fetch the remote review head without rebasing any local branch**

Run:

```powershell
git fetch origin fix/event-loop-blocking-io
git diff --stat main...origin/fix/event-loop-blocking-io
git diff main...origin/fix/event-loop-blocking-io -- agents/core/routers/browser.py
```

Expected: a read-only remote comparison. Do not run `git rebase`, `git merge`, or force operations.

- [ ] **Step 3: Compare each local event-loop commit against the PR path it overlaps**

Run:

```powershell
git diff --no-index -- agents/core/routers/browser.py ../wave1/blocking-browser/agents/core/routers/browser.py
git diff --no-index -- agents/core/cameras/onvif.py ../wave1/blocking-house-onvif/agents/core/cameras/onvif.py
git diff --no-index -- agents/core/routers/memory_kg.py ../wave1/blocking-memorykg/agents/core/routers/memory_kg.py
git diff --no-index -- agents/core/house/actuation.py ../wave2/house-actuator-enqueue/agents/core/house/actuation.py
```

Expected: identify whether each local patch is duplicate, additive, or divergent. A nonzero exit from
`git diff --no-index` means differences exist; it is evidence, not a failure.

- [ ] **Step 4: Record one owner decision for every overlapping path**

Use this decision table in the PR review or approved sprint handoff:

| Path | Allowed decision | Required disposition |
| --- | --- | --- |
| `routers/browser.py` | Keep #945, keep local successor, or explicitly replace both | One PR owns the final code and tests. |
| `cameras/onvif.py` | Keep #945, keep local successor, or explicitly replace both | One PR owns the final code and tests. |
| `routers/memory_kg.py` | Keep #945, keep local successor, or explicitly replace both | One PR owns the final code and tests. |
| `house/actuation.py` | Keep #945, keep local successor, or explicitly replace both | One PR owns the final code and tests. |

Expected: no overlapping local branch is pushed until the table has an approved single owner for its
path. Carry surviving tests into the selected owner branch before closing a duplicate branch.

- [ ] **Step 5: Diagnose #945 CI failures at its exact head**

Run:

```powershell
gh pr checks 945 --watch --fail-fast
gh run view <failing-run-id> --log-failed
```

Expected: attach a root cause and a proposed owner to each failed check. Do not infer failures from
the check name; copy the failing log section into the evidence receipt.

- [ ] **Step 6: Commit only a selected successor branch after authorization**

Run only if the owner approves a selected local successor:

```powershell
git status --short
git add <selected-production-files> <selected-test-files>
git commit -m "fix(runtime): keep selected blocking I/O off the event loop"
```

Expected: one focused rollback unit, no `BACKLOG.md` collision. Do not push in this task.

### Task 2: Prepare the R0 Documentation Truth Refresh

**Files:**
- Source commits: `adf6ba09` and `7d8d9a09`
- Modify: `NERVA_VISION.md`
- Modify: `README.md`
- Create: `docs/FLAGS.md`
- Verify: `scripts/check_ai_workflow_policy.py`

- [ ] **Step 1: Create a clean docs integration branch from current `main`**

Run:

```powershell
git worktree add C:\Users\andrei649\AppData\Local\Temp\opencode\docs-truth-refresh -b docs/truth-refresh main
git -C C:\Users\andrei649\AppData\Local\Temp\opencode\docs-truth-refresh cherry-pick adf6ba0925d76a49af357fc7eed5bf09b26a2449
git -C C:\Users\andrei649\AppData\Local\Temp\opencode\docs-truth-refresh cherry-pick 7d8d9a099ca4cec5f46aed66269314e5673f6a7c
```

Expected: one docs-only worktree with exactly `NERVA_VISION.md`, `README.md`, and `docs/FLAGS.md`
changed. If either cherry-pick conflicts, stop and obtain an explicit ownership decision; do not
resolve by broad reformatting.

- [ ] **Step 2: Recheck the factual citations that control behavior claims**

Run:

```powershell
rg -n "JARVIS_ACTION_KERNEL|JARVIS_UNIFIED_ACTION_API" agents/core/kernel/flags.py agents/core/capability_actions.py
rg -n "whatsapp|signal|matrix|teams|google" agents/core/channels/webhook_channels.py
rg -n "Mediation.KERNEL" agents/core/kernel/registry.py
```

Expected: documentation claims remain aligned with the current source. Correct only a factual drift
found by these commands; do not broaden the documentation pass.

- [ ] **Step 3: Validate the docs-only PR head**

Run:

```powershell
git diff --check main...HEAD
python scripts/check_ai_workflow_policy.py
git diff --stat main...HEAD
```

Expected: no whitespace errors, policy check passes, and only the three planned documentation files
appear in the stat.

- [ ] **Step 4: Conduct independent R0 review and record evidence**

Review checklist:

```text
Every changed factual claim has a current file:line citation.
No product behavior, generated files, or backlog ledger changed.
Signal's external signal-cli requirement and signature-verification host seam remain explicit.
```

Expected: a PR body receipt with head SHA, changed paths, policy check result, reviewer identity,
and `lease=none`.

### Task 3: Convert HUD Seeded-Corpus Honesty Into One R2 PR

**Files:**
- Modify: `frontend/src/api/live.ts`
- Modify: `frontend/src/app.tsx`
- Modify: `frontend/src/data.ts`
- Modify: `frontend/src/modes2.tsx`
- Modify: `frontend/src/modes3.tsx`
- Create: `frontend/src/test/seeded-corpora-honesty.test.tsx`
- Review generated output: `agents/web/v2/index.html`
- Review generated output: `agents/web/v2/assets/index-*.js`

- [ ] **Step 1: Freeze and inspect the current dirty HUD diff before changing it**

Run:

```powershell
git status --short --branch
git diff -- frontend/src/api/live.ts frontend/src/app.tsx frontend/src/data.ts frontend/src/modes2.tsx frontend/src/modes3.tsx
Get-Content frontend/src/test/seeded-corpora-honesty.test.tsx
git diff -- agents/web/v2/index.html agents/web/v2/assets
Get-FileHash agents/web/v2/assets/index-*.js
```

Expected: confirm the source change strips non-demo seed data, restores labeled demo corpus on demo
entry, and renders honest empty states. Do not edit during this inspection.

- [ ] **Step 2: Prove the new regression suite passes at the dirty head**

Run:

```powershell
cmd /c "npx vitest run src/test/seeded-corpora-honesty.test.tsx"
```

Working directory: `frontend`.

Expected: all tests in `seeded-corpora-honesty.test.tsx` pass. If any test fails, fix only the
smallest source defect and rerun this command before broader checks.

- [ ] **Step 3: Run the full frontend evidence set**

Run:

```powershell
cmd /c "npm test"
cmd /c "npm run typecheck"
cmd /c "npm run build"
```

Working directory: `frontend`.

Expected: Vitest exits zero, TypeScript exits zero, and Vite builds. Capture the chunk-size warning
as a warning if present; it is not a passing test result.

- [ ] **Step 4: Decide generated HUD artifact policy from repository evidence**

Run:

```powershell
git log -5 --oneline -- agents/web/v2/index.html agents/web/v2/assets
git ls-files agents/web/v2/index.html agents/web/v2/assets
git check-ignore -v agents/web/v2/index.html agents/web/v2/assets/index-BYIwMnv8.js
```

Expected: classify `agents/web/v2` as either a committed deployment artifact or an accidental local
build output. If it is committed output, include the new index and hashed asset while removing the
superseded tracked asset. If it is not committed output, leave source and test changes only and ask
before deleting any user-owned artifact delta.

- [ ] **Step 5: Commit the selected HUD rollback unit after artifact decision**

Run:

```powershell
git add frontend/src/api/live.ts frontend/src/app.tsx frontend/src/data.ts frontend/src/modes2.tsx frontend/src/modes3.tsx frontend/src/test/seeded-corpora-honesty.test.tsx
git add agents/web/v2/index.html agents/web/v2/assets/<selected-hash>.js
git rm agents/web/v2/assets/<superseded-hash>.js
git commit -m "fix(hud): remove seeded ADMIN and OBSERVE live fallbacks"
```

Expected: stage generated files only when Step 4 proves they are repository-managed deployment
artifacts. If they are not, omit the second `git add` and `git rm` lines. Do not push.

- [ ] **Step 6: Prepare independent R2 review receipt**

Review checklist:

```text
Live rows always come from current backend evidence.
No seeded ADMIN key, backup, channel, host, trace, arena, or by-agent row renders in non-demo mode.
Demo mode restores its labeled corpus when live hydration previously mutated V2 in place.
OBSERVE live proof excludes unrelated Signal Layer health.
```

Expected: PR receipt binds the fresh full frontend commands, head SHA, changed paths, known Vite
warning, reviewer identity, and `lease=none`.

### Task 4: Prepare Codeintel as a Standalone R2 Candidate

**Files:**
- Source branch: `wave/blocking-codeintel` at `0981daeb`
- Modify: `agents/core/routers/codeintel.py`
- Create: `tests/test_codeintel_router_async.py`
- Verify: `tests/test_codeintel.py`
- Verify: `tests/test_codeintel_mcp_tool.py`
- Verify: `tests/test_mcp_route_tools.py`
- Verify: `tests/test_route_parity_guard.py`

- [ ] **Step 1: Confirm that #945 does not claim the codeintel path**

Run:

```powershell
gh pr view 945 --json files --jq '.files[].path'
git show --stat --oneline 0981daeb
```

Expected: `agents/core/routers/codeintel.py` is absent from #945. If it appears, move this candidate
back to Task 1 ownership resolution.

- [ ] **Step 2: Re-run exact-head regression evidence**

Run:

```powershell
python -m pytest tests/test_codeintel_router_async.py tests/test_codeintel.py tests/test_codeintel_mcp_tool.py tests/test_mcp_route_tools.py tests/test_route_parity_guard.py -q
```

Working directory: the `wave/blocking-codeintel` worktree.

Expected: zero failures. The new async test must demonstrate the cold index build/reindex stays off
the event loop; do not accept a timeout-only assertion.

- [ ] **Step 3: Review bounded behavior and commit ancestry**

Run:

```powershell
git diff 75e928114024869bae75ee77937974af9dda5db3...0981daeb -- agents/core/routers/codeintel.py tests/test_codeintel_router_async.py
git log --oneline 75e928114024869bae75ee77937974af9dda5db3..0981daeb
```

Expected: only the router offload and its regression test appear. Record the intentional unaddressed
cold-start cache race as a known limitation, not as a hidden behavior change.

- [ ] **Step 4: Prepare the R2 PR evidence receipt**

Required receipt content:

```text
head=0981daeb3ebcc140d3fe14e4aec14a6ca1c774e0
risk=R2
paths=agents/core/routers/codeintel.py,tests/test_codeintel_router_async.py
tests=the exact command in Step 2 with exit code and pass count
known_limitation=concurrent cold starts can build an immutable cache twice
lease=none
next=independent review
```

Expected: no push until an independent reviewer accepts the exact head.

### Task 5: Complete F14 Runtime Evidence Before PR Readiness

**Files:**
- Source branch: `wave/f14-container-hardening` at `17fda1de`
- Modify candidate: WorldView Dockerfiles and deployment Compose overlays already in that commit.
- Verify: `worldview/docker-compose.yml` plus each deployment overlay.

- [ ] **Step 1: Revalidate all Compose overlays in documented merged mode**

Run:

```powershell
$base = 'worldview/docker-compose.yml'
$overlays = @(
  'worldview/deploy/dr/docker-compose.dr.yml',
  'worldview/deploy/lakehouse/docker-compose.lakehouse.yml',
  'worldview/deploy/observability/docker-compose.observability.yml',
  'worldview/deploy/tiles/docker-compose.tiles.yml'
)
foreach ($overlay in $overlays) { docker compose -f $base -f $overlay config --quiet }
```

Expected: all four commands exit zero. Do not use overlays standalone: DR, lakehouse, and tiles
intentionally depend on services from the base compose file.

- [ ] **Step 2: Verify Docker daemon availability before claiming runtime evidence**

Run:

```powershell
docker version
docker info
```

Expected: both client and server sections succeed. If the server is unavailable, record
`runtime_evidence=blocked_by_docker_daemon` and leave the PR draft.

- [ ] **Step 3: Build and start the backend API when the daemon is available**

Run:

```powershell
Set-Location worldview
docker build -f backend-api/Dockerfile -t worldview-backend-api:f14 .
docker run --rm --name worldview-backend-api-f14 -p 127.0.0.1:18080:4000 worldview-backend-api:f14
```

Expected: image build succeeds and the container starts as its declared non-root user. In a second
shell, verify the real liveness endpoint before stopping the container:

```powershell
Invoke-WebRequest http://127.0.0.1:18080/health -UseBasicParsing
docker inspect --format '{{.Config.User}} {{json .Config.Healthcheck}}' worldview-backend-api-f14
```

Expected: HTTP 200 and a non-root configured user with a healthcheck. The Dockerfile explicitly
requires the `worldview/` build context and exposes port 4000. Stop the foreground container with
Ctrl+C after collecting evidence.

- [ ] **Step 4: Review runtime-compatible hardening deltas**

Run:

```powershell
git diff 75e928114024869bae75ee77937974af9dda5db3...17fda1de -- worldview
git diff --check 75e928114024869bae75ee77937974af9dda5db3...17fda1de
```

Expected: only Dockerfile and deployment Compose hardening changes. Confirm every `read_only` image
has the declared writable tmpfs or volume path it needs and every TLS requirement has a documented
operator escape hatch.

- [ ] **Step 5: Prepare F14 as draft or review-ready based on Step 2**

Use exactly one state:

```text
delivery=draft ci=compose_validated governance=review_required runtime=blocked_by_docker_daemon
```

or:

```text
delivery=review_ready ci=compose_validated governance=review_required runtime=backend_build_and_health_passed
```

Expected: do not mark the PR ready or merge it while only static Compose evidence exists.

### Task 6: Hold and Re-scope R3 Security Work

**Files:**
- Hold: `wave/qa4-ungoverned-counter` at `8fd144ea`
- Hold: `wave/ssrf-pinning-nav` at `8c06f471`
- Inspect: `agents/core/autonomy/worker.py`
- Inspect: `agents/core/kernel/binding.py`
- Inspect: `agents/core/kernel/metrics.py`
- Inspect: `agents/core/http_client.py`
- Inspect: `agents/core/plugins/websearch.py`

- [ ] **Step 1: Assign independent R3 roles before review starts**

Record this in the handoff:

```text
QA4 builder=<wave builder> reviewer=<independent reviewer> integrator=<different owner>
SEC-B4 builder=<wave builder> reviewer=<independent reviewer> integrator=<different owner>
```

Expected: no person or agent fills both builder and integrator roles for either slice.

- [ ] **Step 2: Review QA4 against the persisted-evidence invariants**

Run:

```powershell
python -m pytest tests/test_qa4_ungoverned_counter.py tests/test_kernel_metrics.py tests/test_audit_gates_measure_substance.py -q
git diff 75e928114024869bae75ee77937974af9dda5db3...8fd144ea -- agents/core/autonomy/worker.py agents/core/kernel/binding.py agents/core/kernel/metrics.py agents/core/capability_actions.py agents/core/routers/analytics.py
```

Expected: reviewer verifies all of the following from code and tests: task evidence persists from
enqueue to execution; a mediated task cannot bless a later bypass in the same worker tick; a queued
governed task in a later context is not counted; missing evidence increments an observational
counter and never changes authorization behavior.

- [ ] **Step 3: Record SEC-B4 as preflight-only and prevent an incorrect security claim**

Run:

```powershell
python -m pytest tests/test_http_client_ssrf_pinning.py tests/test_http_client.py tests/test_plugin_egress.py tests/test_egress_audit_b3.py tests/test_egress_kernel_wave.py tests/test_browser_agent_nav_async.py tests/test_h15_1_browser_agent.py -q
git show --stat 590380b2
git show --stat 8c06f471
```

Expected: retain the browser-agent DNS offload as a potentially separable R2 candidate. Mark the
PluginHTTPClient change as `preflight_validation_only`: httpx can resolve again at connect time, so
it does not close the rebinding TOCTOU gap.

- [ ] **Step 4: Create a dedicated SEC-B4 transport-pinning design before new code**

The design must define a connection mechanism that dials the validated address while preserving
TLS Server Name Indication and Host header semantics. It must state one of these two valid paths:

```text
Use a custom httpx transport that connects to the validated IP while retaining the original host
for TLS verification and HTTP Host, then prove no second DNS lookup occurs before connect.
```

or:

```text
Use the existing websearch pinned-netloc mechanism only if it demonstrably prevents a second DNS
lookup in PluginHTTPClient's actual httpx transport path and preserves TLS semantics.
```

Expected: a new R3 design is approved before implementation. Do not push or label `8c06f471` as a
completed SEC-B4 fix.

### Task 6A: Replace QA4 With Authenticated Intake Evidence

**Files:**
- Create replacement branch from `main`: `fix/qa4-authenticated-evidence`
- Modify: `agents/core/autonomy/mediation.py`
- Modify: `agents/core/autonomy/queue.py`
- Modify: `agents/core/autonomy/worker.py`
- Modify: `agents/core/kernel/binding.py`
- Modify only if required for actual House intake: `agents/core/house/actuation.py`, `agents/core/routers/house.py`
- Test: `tests/test_qa4_ungoverned_counter.py`
- Test: `tests/test_task_mediation_evidence.py`
- Test only if House intake changes: focused house actuation tests

The owner approved a replacement, not an amendment, for `8fd144ea`. The new evidence is outside
caller-controlled payload: it is persisted in SQLite and signed over version, unique intake ID,
agent, kind, title, effective origin, canonical payload digest, kernel verdict, tier, and issue time.
Execution verifies the signature and all live task fields only to determine whether it increments an
observational breach counter; invalid evidence never blocks an action.

Required failing-first cases:

```text
A forged payload["kernel_mediation"] cannot suppress a breach count.
An owner edit to task payload, title, kind, agent, or origin invalidates prior evidence and counts.
One bridge decision cannot bless two queued tasks.
A durable valid evidence record survives a worker restart with the stable signer.
House control/security receives a real intake kernel decision and is not falsely counted.
```

The replacement preserves B7 receipt behavior, preserves execution-time House kernel checks, and
does not accept legacy payload markers.

### Task 6B: Replace SEC-B4 With Pinned Plugin Transport And Browser Fail-Closed Gate

**Files:**
- Create replacement branch from `main`: `fix/secb4-pinned-plugin-egress`
- Modify: `agents/core/http_client.py`
- Modify only if needed: `agents/core/security/ssrf.py`
- Modify: `agents/core/browser_agent.py`
- Modify: `agents/core/browser_playwright.py`
- Test: `tests/test_http_client_ssrf_pinning.py`
- Test: `tests/test_browser_agent_nav_async.py`
- Test: focused Playwright-driver and SSRF suites

PluginHTTPClient must dial the validated literal IP, preserve logical Host and TLS SNI, set
`trust_env=False`, and validate/pin every redirect. Scripted DNS plus recording transport tests must
assert the actual dial target, Host, and SNI fields.

Browser HTTP(S) navigation must fail closed before dispatch when a transport-bound pinning proxy is
not injected. DNS/validator errors result in zero driver calls. The current Playwright route guard is
not considered pinning and must not be described as such. Browser DNS work remains off the async loop.

### Task 7: Assemble Exact-Head Receipts and Ask for PR Authorization

**Files:**
- Review: selected branch and PR body only.
- Update later, after authorization: `BACKLOG.md` in the one PR that actually closes each item.

- [ ] **Step 1: Build one receipt per candidate branch**

Use this template exactly:

```text
policy_version=<from .github/ai-development-policy.json>
head=<40-character SHA>
risk=<R0|R2|R3>
paths=<comma-separated changed paths>
commands=<command; exit code; concise result>
producer=<builder identity>
reviewer=<independent reviewer or pending>
known_gaps=<none or explicit list>
lease=none
generated_at=<ISO-8601 time>
```

Expected: evidence references only commands run after the final commit for that candidate head.

- [ ] **Step 2: Check remote overlap before requesting PR creation**

Run:

```powershell
gh pr list --state open --limit 100 --json number,title,headRefName,baseRefName,url
git status --short --branch
```

Expected: no candidate duplicates an open PR path. Dirty worktrees are committed or explicitly
parked before a PR is requested.

- [ ] **Step 3: Request one explicit owner decision per remote mutation**

Ask for authorization in this form:

```text
Authorize push and draft PR creation for:
1. docs/truth-refresh (R0)
2. fix/admin-observe-seeded-corpora (R2)
3. fix/codeintel-event-loop (R2)
4. chore/worldview-f14 (R2 draft only if runtime evidence is incomplete)
```

Expected: no `git push`, `gh pr create`, PR edit, or merge occurs without the requested explicit
authorization. R3 candidates are omitted until their independent integrator accepts them.

## Plan Self-Review

Spec coverage:

- #945 ownership: Task 1.
- Independent docs, HUD, codeintel, and F14 closure: Tasks 2 through 5.
- R3 QA4 and SEC-B4 hold: Task 6.
- Exact-head evidence and push authorization: Task 7.

Placeholder scan: clear; every command and acceptance condition is explicit.

Type and path consistency: every branch head, source path, test path, and risk label matches the
approved sprint design as of base `75e928114024869bae75ee77937974af9dda5db3`.
