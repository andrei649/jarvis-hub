# TODO / Next-Session Handoff

> **Purpose:** start a new session from here. Captures open work, things that were
> **missed**, and — importantly — **other sessions running in parallel** so you
> don't collide. Generated 2026-06-04 against `main` @ v9.9.9.
>
> **Read this first, then check the live state** (`git fetch`, list open PRs) — the
> in-flight items below may have moved.

---

## ⚠️ Concurrent / in-flight sessions — DO NOT collide

Multiple Claude sessions have been working this repo simultaneously. Before
touching a file, check whether another session owns it.

| Branch / PR | What it's doing | Coordination |
|-------------|-----------------|--------------|
| **PR #130** (draft) · `claude/fix-hud-frontend-tests` | Fixing the 2 frontend tests broken by the HUD redesign (TopBar `COG/SYS` buttons removed; `AgentsGrid` removed). Reportedly green locally (24 passed, coverage 65.76%). | **Owns `tests/frontend/`.** Don't edit frontend tests until this merges. Let that session finish + merge it. |
| `claude/project-status-report-rosXA` (no open PR last checked) | A status/roadmap session that edited **`BACKLOG.md`** (promoting H13–17 from "proposed" into the formal roadmap + totals). | **Owns `BACKLOG.md` edits.** Coordinate before editing the roadmap/Status tables, or you'll conflict. |
| **PR #119 / #120** (dependabot) | `actions` group bump + `uvicorn` requirement bump. | Review & merge when convenient; not session work. |
| ~93 stale `claude/*` branches | Squash-merged feature branches, never deleted. | Safe to prune (see housekeeping). |

**Rule of thumb:** this repo squash-merges one feature per PR off fresh `main`.
Always branch from up-to-date `origin/main`; rebase if you branched before another
PR merged (we hit a merge conflict once from branching off an un-merged branch).

---

## Where things stand (reality, not the stale status report)

- **Version `v9.9.9`** = the pre-1.0 "audit gate". The *software* backlog is **mostly**
  shipped (Waves 1–10 + H13.2/H14.x/H16.x/H17.x), but **not 100%** — see P1 below.
- **~123 backlog items ✅** done. Full Python suite green (~1,520 passed, 9 skipped).
- **Audit done** (`docs/AUDIT.md`); P0 cleanups applied (JsonStore base, ComponentRegistry,
  micro-bugs, A7 persistence, Q3/Q4/Q7). `web.py` router split (A1) still deferred.
- **HUD redesigned** (PRs #121–#129): clean TopBar (status · ▦ Console · ⚙), ⚙ Settings,
  ▦ Console with **20 feature panels**, admin-token wired (HUD + `/admin`), cache-bust fixed.

---

## P0 — correctness / live regressions

1. **Frontend tests + CI** — **being handled by PR #130.** Verify it merges and the
   `frontend` CI job (`ci.yml` → `npm run test:coverage`) goes green. The HUD redesign
   (8 PRs) was merged with **only Python + `node --check`** verification; the vitest
   suite was never run by the redesign sessions. After #130: confirm `main`'s frontend
   CI is green.

2. **Add tests for the new HUD code** — `console.js` + `tools.js` (the ⚙ Settings menu
   + 20 Console panels) have **zero automated coverage** (~480 LOC). Add `tests/frontend/`
   specs (SettingsMenu renders + writes localStorage; ConsoleOverlay nav; a couple of
   panels mock-fetch + render). The harness is `tests/frontend/harness.js` (jsdom).

3. **`docs/MANUAL_TESTING.md` §C — render-test the 20 Console panels.** Nobody has
   clicked through them in a browser. Open ▦ Console, sweep every panel, try round-trips
   (Arena run+vote, Notes save, Rooms message, a Tools admin action with a token set).
   Paste any red console error.

---

## P1 — buildable backlog that was MISSED (the "all software shipped" claim is false)

README.md/STATUS.md currently say "the entire software backlog is shipped." **Not true** —
these are pure-software and were skipped:

4. **H10.7 — AI-Assisted Workflow Builder** — in the Visual Builder, a "describe what this
   step should do" field → LLM generates a `WorkflowStep` config (agent/tool/prompt),
   then validate via the existing pipeline schema. Backend endpoint + a Console/Builder field.
5. **H10.26 — Data Spaces / Agent Data Scope** — organize data sources (memory segments,
   plugin outputs, KG) into "spaces" with per-agent permissions; complement to
   `LOCAL_ONLY_AGENTS`. A scoping/permission layer.
6. **H12.12 — signed skills marketplace** — `skills/signing.py` already exists; likely a
   thin extension (signatures + review gate on import). Verify scope, then finish.

→ Either **build #4–#6** and make the claim true, or **soften the wording** in README/STATUS.

7. **HUD "every feature has a home" is incomplete** — ~12 endpoint groups still have **no
   Console panel**: cost/analytics, eval datasets, reflection, oracle, OAuth,
   agent-templates, local-docs, **security (audit log / capabilities / kill-switch)**,
   models, trust, resilience. The **kill-switch & capability tokens have no UI** — notable
   for a "governed" product. Add panels (each ~30–50 LOC via the `tools.js` registry).

---

## P2 — housekeeping (flagged repeatedly, still open)

8. **Delete ~93 stale `claude/*` remote branches** (squash-merged). `git branch -r | grep
   origin/claude/` → prune.
9. **`apscheduler` not in core requirements** — scheduled jobs (NL-schedule, learning-loop
   cron, heartbeats) + 4 `test_heartbeat.py` tests are **inert** without it. Add to
   `requirements`/`pyproject` (or `[autonomy]` extra) so local runs match CI.
10. **8 skipped `tests/test_spotify.py`** — `agents/core/skills/spotify.py` not implemented.
    Either implement the module or remove the skipped tests.
11. **v1.0 scope contradiction unresolved** — MOONSHOT §4 (Trustworthy gate met *now*) vs
    BACKLOG roadmap (v1.0 needs H10+H11+H12). Decide: tag v1.0 at the Trustworthy gate and
    move the rest to v1.x, **or** keep the broad gate. The `9.9.9` framing sidesteps it.
12. **Data concern (from screenshot analysis):** the `/ticker` prints a full **IBAN** in
    plaintext (`GECKO · ... RO12INGB0987654321`). It's **mock/seed data** today
    (`balance.py`), but if `BalanceReaderPlugin` is ever wired to a real account, the HUD
    would broadcast a real IBAN — and the PII scanner specifically flags RO IBANs. **Mask
    it** (e.g. `…4321`) before going live.

---

## Genuinely DEFERRED — needs hardware / models / external surfaces (don't attempt blind)

- **H11.1–4** Tauri desktop · Rust hot-path crate · SFT/GRPO training · WASM sandbox.
- **H13.1/3/4** strict-local VLM (Qwen3-VL GGUF) · speculative decoding · MoE model refresh.
- **H15.1/2/3** browser-use · screen-grounding (UI-TARS) · isolated desktop operator.
- **H16.2/3** A2A endpoint · agentic payments (network surfaces, off by default).
- **H12.7/8/13/14** passive multi-surface capture · mic-satellite→GPU split · E2E device sync · small fine-tuned model.
- **H13.2 enforcement** (GBNF generation shipped; passing `grammar=` to llama.cpp needs the model backend) · **H16.1 federated MCP auth** (local self-issued tokens shipped; external IdP is a verification-backend swap).

---

## Useful pointers
- Audit + fix-phase log: `docs/AUDIT.md` (§7 = what's done/deferred).
- Manual test checklist: `docs/MANUAL_TESTING.md`.
- HUD redesign plan/IA: `docs/HUD_PLAN.md`.
- Console panel registry (add new feature UIs here): `agents/web/static/tools.js` → `TOOLS`.
- Backlog truth: `BACKLOG.md` (✅ = done) — but **another session may be editing it** (see top).
