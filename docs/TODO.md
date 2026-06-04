# TODO / Next-Session Handoff

> **Purpose:** start a new session from here. Captures open work, things that were
> **missed**, and — importantly — **other sessions running in parallel** so you don't collide.
>
> Generated 2026-06-04 against `main` @ v9.9.9. **Reconciled 2026-06-04 in PR #132** against
> the verified codebase — stale items were corrected (marked _updated_ / ~~struck~~). Always
> re-check live state (`git fetch`, list open PRs) before acting; in-flight items move fast.

---

## ⚠️ Concurrent / in-flight sessions — DO NOT collide

Multiple Claude sessions have worked this repo simultaneously. Before touching a file,
check whether another session owns it.

| Branch / PR | What it's doing | Coordination |
|-------------|-----------------|--------------|
| **PR #132** (draft) · `claude/lucid-goodall-R7AjJ` | Doc-truth fix: the BACKLOG summary table read H10 0/30 etc. while the detail shows ~82% done — corrected README / STATUS / BACKLOG / GO_LIVE_PLAN. **Carries this file.** | Touches the 4 status docs. |
| **PR #131** (draft) · `claude/docs-todo-handoff` | The original of this handoff doc. | **Superseded** by the reconciled copy in #132 — close one. |
| ~~PR #130~~ ✅ **merged** · `claude/fix-hud-frontend-tests` | Fixed the 2 frontend tests broken by the HUD redesign. | **Lock released** — `tests/frontend/` is free to edit again. |
| `claude/project-status-report-rosXA` (no open PR) | Status/roadmap session that promoted H13–17 into the BACKLOG roadmap. | Its edits are merged; PR #132 further corrected the Status tables. |
| `claude/v1.0-release-prep` (no open PR) | **Stale divergent branch** (tip 2026-06-02, predates the 2026-06-03 wave). Its big diff-vs-`main` is the wave it never had — **not** a rollback. | Ignore unless revived (needs a full rebase). |
| ~~#119 / #120~~ ✅ merged (dependabot) | actions bump + uvicorn bump. | Done. |
| ~27 stale `origin/claude/*` branches | Squash-merged feature branches, never deleted. | Safe to prune (P2). |

**Rule of thumb:** squash-merge one feature per PR off fresh `main`. Always branch from
up-to-date `origin/main`; rebase if you branched before another PR merged.

---

## Where things stand (verified 2026-06-04)

- **Version `v9.9.9`** = the pre-1.0 **audit gate**: code is written but **not yet
  audit-verified / manually tested**. That's the gate — not a claim of bug-free.
- **Backlog: ~166/186 items ✅ code-complete (≈82% SP).** The 2026-06-03 wave shipped most
  of H10 (27/30), H12 (10/15), H14, H16, H17. _(The summary table previously read ~0% for
  these — fixed in PR #132; the detail rows were always correct, and the modules + per-item
  tests exist on disk.)_
- **Open work is small and mostly hardware/models/network**; a few pure-software P3 items
  remain (see P1).
- **Audit done** (`docs/AUDIT.md`); P0 cleanups applied. `web.py` router split (CLN-3 / A1) deferred.
- **HUD redesigned** (PRs #121–#129): TopBar (status · ▦ Console · ⚙), ⚙ Settings, ▦ Console
  with 25 feature panels (incl. a Security group), admin-token wired, cache-bust fixed.

---

## P0 — correctness / live regressions

1. **Frontend CI** — PR #130 ✅ merged (fixed the 2 stale tests). _Action: confirm `main`'s
   `frontend` CI job (`ci.yml` → `npm run test:coverage`) is green._ The HUD redesign (8 PRs)
   merged with only Python + `node --check`, so vitest first ran via #130.

2. ~~Add tests for the new HUD code (`console.js` + `tools.js`)~~ ✅ **Done 2026-06-04** —
   `tests/frontend/{console,tools}.test.js` (21 specs) exercise the real shipped artifacts in
   JSDOM: fetch helpers, SettingsMenu, the full Console-panel sweep, and admin flows.
   **console.js 0→97% lines · tools.js 0→71%**; HUD line coverage ~67% (≥60% CI gate).

3. **`docs/MANUAL_TESTING.md` §C — render-test the 20 Console panels** in a real browser (Arena
   run+vote, Notes save, Rooms message, a Tools admin action with a token). Nobody has clicked
   through them; paste any red console error.

---

## P1 — buildable backlog still open (pure software, all P3)

_PR #132 already softened the README/STATUS "entire software backlog shipped" wording to match
reality. What's left to actually **build**:_

4. **H10.7 — AI-Assisted Workflow Builder** — Visual Builder field "describe this step" → LLM
   generates a `WorkflowStep` config; validate via the existing pipeline schema.
5. **H10.26 — Data Spaces / Agent Data Scope** — organize data sources (memory, plugin outputs,
   KG) into "spaces" with per-agent permissions; complements `LOCAL_ONLY_AGENTS`.
6. **H12.12 — signed skills marketplace** — `skills/signing.py` exists; likely a thin extension
   (signatures + review gate on import). Verify scope, then finish.

7. **HUD "every feature has a home"** — _2026-06-04: added a **Security** group (Kill-Switch,
   Trust Scorecard, Capability Tokens, Audit & Intent), **Cost & Usage**, plus **Local Docs,
   Local Models, Agent Templates, Daily Reflection** — Console registry 20→29, all tested._
   **Still missing:** the eval-dataset regression view (`/api/eval/datasets`). (OAuth, Oracle,
   Resilience already have a home in the Systems panel.) Add via `tools.js` `TOOLS` (~30–50 LOC each).

---

## P2 — housekeeping

8. **Prune ~27 stale `origin/claude/*` branches** (squash-merged). _(Handoff said "~93"; current
   count is ~27.)_ `git branch -r | grep origin/claude/` → delete the merged ones.
9. ~~`apscheduler` missing from requirements~~ ✅ **already present** — `requirements.txt:4` **and**
   `requirements-beta.txt:6` (`apscheduler>=3.11.2`). _The handoff was wrong here; no action needed._
10. **9 skipped `tests/test_spotify.py`** — `agents/core/skills/spotify.py` not implemented (Spotify
    ships via `skills/spotify/main.py`). Remove the dead tests (BACKLOG **CLN-1**) or implement the module.
11. **v1.0 scope contradiction** — MOONSHOT §4 (Trustworthy gate met) vs BACKLOG roadmap
    (v1.0 = H10+H11+H12+H13–17). Decide: tag v1.0 at the Trustworthy gate + move the rest to v1.x,
    **or** keep the broad gate. The `9.9.9` framing currently sidesteps it.
12. **Reconcile the test count** — docs disagree: README/STATUS "1,480+", GO_LIVE_PLAN "1,184+",
    this handoff "~1,520". Run the suite, pick the true number, single-source it (ties to H7.8 doc-truth).
13. **Mask the IBAN in `/ticker`** — `balance.py` seed data prints a full RO IBAN
    (`RO12INGB0987654321`). **Mock today** (and not even valid IBAN length), but if
    `BalanceReaderPlugin` is ever wired to a real account the HUD would broadcast a real IBAN —
    and the PII scanner flags RO IBANs. Mask (e.g. `…4321`) before real wiring / go-live.

---

## Genuinely DEFERRED — needs hardware / models / external surfaces (don't attempt blind)

- **H11.1–4** Tauri desktop · Rust hot-path crate · SFT/GRPO training · WASM sandbox.
- **H13.1/3/4** strict-local VLM (Qwen3-VL GGUF) · speculative decoding · MoE model refresh.
- **H15.1/2/3** browser-use · screen-grounding (UI-TARS) · isolated desktop operator.
- **H16.2/3** A2A endpoint · agentic payments (network surfaces, off by default).
- **H12.7/8/13/14** passive multi-surface capture · mic-satellite→GPU split · E2E device sync · small fine-tuned model.
- **H13.2 enforcement** (GBNF generation shipped; passing `grammar=` to llama.cpp needs the model backend) ·
  **H16.1 federated MCP auth** (local self-issued tokens shipped; external IdP is a verification-backend swap).

---

## Useful pointers
- Audit + fix-phase log: `docs/AUDIT.md` · Manual checklist: `docs/MANUAL_TESTING.md` · HUD IA: `docs/HUD_PLAN.md`.
- Console panel registry (add feature UIs here): `agents/web/static/tools.js` → `TOOLS`.
- Backlog truth: `BACKLOG.md` → **Status General** (corrected in PR #132).
