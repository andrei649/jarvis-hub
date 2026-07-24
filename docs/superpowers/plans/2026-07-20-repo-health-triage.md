# Repo Health Triage — 4 Attention Points

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Resolve the 4 attention points identified in the repo health evaluation: verify the security correctness wave, sync stale dependencies, audit the backlog for drift, and assess the H23 release gates.

**Architecture:** These are operational/triage tasks, not features. Each task is independent and can be executed in any order. Tasks 1-3 are agent-executable; Task 4 is owner-gated (assessment only).

**Tech Stack:** Git, pytest, npm, the existing BACKLOG.md/STATUS.md docs.

---

## Task 1: Verify the Security Correctness Wave

**Context:** The `codex/security-correctness-wave` branch has 8 commits ahead of `origin/main` touching security-critical code (`guardrails.py`, `gemini.py`, `gemini_cache.py`, `anthropic.py`, `orchestrator.py`, `autonomy/worker.py`). Tests have not been run locally. The branch must be verified before merge.

**Files:**
- Modified: `agents/core/security/guardrails.py` (guardrails binding, `GuardrailBindingError`, `bind_guardrails`, `BoundGuardrailsEngine`)
- Modified: `agents/core/llm/gemini.py` (Gemini cache request-scoping, auth isolation)
- Modified: `agents/core/llm/gemini_cache.py` (context cache lifecycle)
- Modified: `agents/core/llm/anthropic.py` (Claude defaults alignment)
- Modified: `agents/core/orchestrator.py` (route preservation through guardrails)
- Modified: `agents/core/autonomy/worker.py` (trusted task policy metadata)
- Modified: `agents/core/llm/auth_rotation.py`, `agents/core/llm/provider_errors.py`, `agents/core/llm/gemini_context.py` (new modules)
- Test files: `tests/test_guardrails_generate_kwargs.py`, `tests/test_gemini_cache.py`, `tests/test_gemini_request_context.py`, `tests/test_gemini_secret_safety.py`, `tests/test_claude_model_truth.py`, `tests/test_route_preserving_guardrails.py`, `tests/test_orchestrator_gemini_cache.py`, `tests/test_autonomy_metadata_integrity.py`

- [ ] **Step 1: Confirm we're on the right branch with clean tree**

```bash
git status
git branch --show-current
```

Expected: branch = `codex/security-correctness-wave`, tree clean.

- [ ] **Step 2: Rebase on latest origin/main**

```bash
git fetch origin
git rebase origin/main
```

Expected: clean rebase (or resolve any conflicts from the 5 dependency-bump commits on main).

- [ ] **Step 3: Run the full backend test suite**

```bash
python -m pytest tests/ -v --tb=short 2>&1 | Select-Object -Last 30
```

Expected: all tests pass (~5,300+ collected). Look for any new failures introduced by the security wave commits.

- [ ] **Step 4: Run focused security-related tests**

```bash
python -m pytest tests/test_guardrails_generate_kwargs.py tests/test_gemini_cache.py tests/test_gemini_request_context.py tests/test_gemini_secret_safety.py tests/test_claude_model_truth.py tests/test_route_preserving_guardrails.py tests/test_orchestrator_gemini_cache.py tests/test_autonomy_metadata_integrity.py -v --tb=short
```

Expected: all pass. These are the new/modified test files from the branch.

- [ ] **Step 5: Run Ruff lint on changed files**

```bash
python -m ruff check agents/core/security/guardrails.py agents/core/llm/gemini.py agents/core/llm/gemini_cache.py agents/core/llm/anthropic.py agents/core/orchestrator.py agents/core/autonomy/worker.py
```

Expected: clean (no lint errors).

- [ ] **Step 6: Run py_compile on changed modules**

```bash
python -c "import py_compile; [py_compile.compile(f, doraise=True) for f in ['agents/core/security/guardrails.py','agents/core/llm/gemini.py','agents/core/llm/gemini_cache.py','agents/core/llm/anthropic.py','agents/core/orchestrator.py','agents/core/autonomy/worker.py']]"
```

Expected: no compile errors.

- [ ] **Step 7: Review the guardrails binding change specifically**

Read `agents/core/security/guardrails.py` — verify that `bind_guardrails()` is safe (it creates a new `GuardrailsEngine` wrapping the backend, no state leakage). Verify `_bound_backend()` raises `GuardrailBindingError` when no backend is bound (fail-closed).

- [ ] **Step 8: Decision — merge or fix**

If all green: merge to main (squash or rebase per convention). If failures: identify the failing test, read the commit that introduced it, fix, re-run.

---

## Task 2: Sync Stale Dependencies on origin/main

**Context:** `origin/main` has 5 dependency-bump commits (actions, npm-worldview, npm-frontend, python-deps, npm-worldview-mcp) that are behind the current branch. These are low-risk but should be synced before any merge.

**Files:**
- Modified by bumps: `.github/third-party-manifest.json`, `frontend/package.json`, `mobile/package.json`, `worldview/package.json`, `requirements-beta.txt` (or similar)

- [ ] **Step 1: Check what the bumps actually changed**

```bash
git log origin/main --oneline -5
git diff HEAD..origin/main --stat
```

Expected: only dependency version bumps, no logic changes.

- [ ] **Step 2: Verify frontend tests still pass after rebase**

After the rebase in Task 1 Step 2, the dependency bumps are already included. Verify:

```bash
cd frontend; npm test -- --run 2>&1 | Select-Object -Last 10
```

Expected: ~370 tests pass.

- [ ] **Step 3: Verify mobile tests still pass**

```bash
cd mobile; npm test 2>&1 | Select-Object -Last 10
```

Expected: ~93 tests pass.

- [ ] **Step 4: Verify WorldView tests still pass (if applicable)**

```bash
cd worldview; npm test 2>&1 | Select-Object -Last 10
```

Expected: passes (or at minimum, no new failures from the bumps).

- [ ] **Step 5: Check for Dependabot alerts**

```bash
gh api repos/{owner}/jarvis-hub/dependabot/alerts --jq '.[].state' 2>$null | Group-Object
```

Expected: note any open high/critical alerts. The A3 gate already tracks this (4 high alerts as of 2026-07-07, mostly dev-chain).

---

## Task 3: Backlog Drift Audit

**Context:** BACKLOG.md is ~2000 lines. The version roadmap, release gates, and H23 items need a quick scan to confirm priorities haven't drifted from the moonshot. This is a read-only audit, not a rewrite.

**Files:**
- Read: `BACKLOG.md` (full), `MOONSHOT.md` (§4, §5, §6), `STATUS.md`

- [ ] **Step 1: Read the version roadmap section**

Read `BACKLOG.md` lines 276–340 (the Version Roadmap + Forward Roadmap table). Confirm:
- The version-per-minor plan is still coherent (0.11.0 → 0.12.0 → ... → 1.0.0)
- No new versions were inserted without a gate
- The 1.0 gate still requires both proof track (2a) AND AI-OS (2b)

- [ ] **Step 2: Read the H23 roll-up**

Read `BACKLOG.md` lines 448–486 (H23 items). Confirm:
- All ✅ items are actually code-complete (spot-check 2-3 items against `git log --oneline --all --grep`)
- The 🟡 partial items have clear next steps documented
- No items silently regressed from ✅ to 🟡

- [ ] **Step 3: Read the Lane A release gates**

Read `BACKLOG.md` lines 222–234 (Lane A — owner critical path). Confirm:
- A1 (governed-autonomy demo) is still the critical path
- A7 (design partners) timeline is realistic
- A8 (AI-OS v1 owner-host proof) scope hasn't crept
- No new gates were added outside this list

- [ ] **Step 4: Cross-check MOONSHOT.md §4 against BACKLOG.md**

Read `MOONSHOT.md` lines 86–107 (Phase table). Confirm:
- Phase 2a (proven core) and Phase 2b (AI OS) are still the active phases
- The gate expanded decision (2026-07-11) is still reflected in both docs
- No drift between the moonshot and the backlog

- [ ] **Step 5: Check for orphaned items**

Grep BACKLOG.md for any items that reference modules/features that no longer exist:

```bash
# Quick check: any references to removed files?
git diff origin/main..HEAD --name-only --diff-filter=D
```

Expected: only renamed files (`JARVIS.md` → `NERVA.md`), no deleted features.

- [ ] **Step 6: Write drift summary**

If drift found: note it in a comment on this plan or create a short `docs/superpowers/plans/2026-07-20-backlog-drift-notes.md`. If clean: confirm "no drift detected" and move on.

---

## Task 4: H23 Release Gates Assessment

**Context:** The H23 release gates (A1–A9) are the bottleneck to 1.0. This is an owner-gated assessment — the agent can audit status but cannot execute the owner-only items. The key question: what's the actual critical path?

**Files:**
- Read: `BACKLOG.md` lines 222–246 (Lane A + Lane B)
- Read: `docs/MANUAL_TESTING.md` (what A1 requires)
- Read: `docs/OWNER_TASKS.md` (what only the owner can do)

- [ ] **Step 1: Map each Lane A gate to its actual blocker**

For each of A1–A9, identify:
- What's done vs. what's remaining
- What's blocking it (code? owner action? hardware? design partners?)
- Estimated effort (days/weeks)

Write the assessment as a table:

| Gate | Status | Blocker | Owner Action Needed | ETA |
|------|--------|---------|---------------------|-----|
| A1 | ⬜ | ... | ... | ... |
| A2 | ⬜ | ... | ... | ... |
| ... | ... | ... | ... | ... |

- [ ] **Step 2: Identify the true critical path**

The critical path is the longest chain of sequential owner-dependent items. Likely:
- A1 (governed-autonomy demo) → A2 (72h soak) → A7 (design partners ≥2 weeks) → A9 (tag 1.0.0)
- A8 (AI-OS owner-host proof) runs in parallel but is also blocking A9

Confirm: which path is longer? That's the real bottleneck.

- [ ] **Step 3: Check what AI-OS pillars are code-complete vs. owner-gated**

From STATUS.md lines 64–69:
- H28 (governed operator) — hermetic done, owner-live gate pending
- H29 (Media Director) — merged, hermetic done
- H30 (House Brain) — merged, hermetic done, real HA needs owner hardware
- H31 (Camera Intelligence) — merged, hermetic done, Frigate needs owner hardware
- H32 (Capability Acquisition) — merged, hermetic done
- H33 (Ambient Intelligence) — merged, hermetic done

All 6 AI-OS pillars are code-complete. The bottleneck is **real hardware validation** (A8), not code.

- [ ] **Step 4: Read the live-vs-plumbing audit**

Read `docs/research/2026-07-18-live-vs-plumbing-capability-audit.md` (the first ~50 lines). This audit identified ~11 LIVE, ~52 PLUMBING, ~14 STUB capabilities. The Tranche 1 fixes are done. Confirm:
- The "Config-wins" items (Google OAuth, Spotify, etc.) are owner-actionable
- The "Genuinely unbuilt" items don't block 1.0 (they're post-1.0 or owner-gated)

- [ ] **Step 5: Write the assessment summary**

Save to `docs/superpowers/plans/2026-07-20-h23-gates-assessment.md` with:
- The gate table from Step 1
- The critical path analysis from Step 2
- A recommendation: what should the owner focus on first?
- A realistic timeline estimate for reaching 1.0

---

## Execution Notes

**Order:** Tasks 1 and 2 can run in parallel (verify branch + check deps). Task 3 is independent read-only. Task 4 depends on Task 3's drift audit being clean.

**Who executes:** Tasks 1–3 are agent-executable. Task 4 is agent-authored but owner-decided (the ETA and priority calls require owner judgment).

**Merge strategy:** If Task 1 passes, the security correctness wave should be merged to main via PR (squash merge). The 8 commits on the branch are: design docs (2) + security fixes (6) + status resync (1). The PR should reference the security-correctness-wave design spec at `docs/superpowers/specs/2026-07-15-security-correctness-wave-design.md`.
