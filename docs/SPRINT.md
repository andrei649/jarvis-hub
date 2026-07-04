# SPRINT.md — stare partajată între agenți (sesiune curentă)

> Fișier viu. Actualizat de conductor agent sau lead agent după fiecare wave.
> La start de sesiune: copiază template-ul de mai jos și completează câmpurile.

---

## Sesiune curentă

**Data:** 2026-07-04 (ORIZONT 26 P2.5 Install Smoke Path)
**Lead agent / Conductor:** Codex
**Obiectiv sesiune:** continue the ORIZONT 26 plan after P2.4; start P2.5 Install Smoke Path as one focused PR with docs/status kept current.
**Branch:** `main` (next branch: `codex-o26-p2-5-install-smoke`)

**Scope decision (2026-07-04):** O26-P0, P1.1, P2.1, P2.2, P2.3, and P2.4 are now merged. The
next unblocked plan item is O26-P2.5 Install Smoke Path. Keep it one item = one PR: no HUD breadth or
product-posture wave 2 work in that branch.

**Previous session:** O26-P0.1 golden harness was merged via #496, with P0.2–P0.7 already completed on
main by parallel agents.

---

## Wave-uri active

| Wave | Branch | PR | Status | Agenți | Note |
|------|--------|----|--------|--------|------|
| O26-P1.1 / one-turn pipeline | `codex-o26-p1-1-one-turn-pipeline` | #498 | ✅ merged | Codex | Shared prompt wrapper + shared post-turn record seam |
| O26-P2.1 / env config consolidation | `claude/jarvis-hub-backlog-review-jx87gz` | #500 | ✅ merged | Claude/Fable | One `env_config.truthy()` and env parse ratchet |
| O26-P2.2 / memory consolidation | `codex-o26-p2-2-memory-consolidation` | #501 | ✅ merged | Codex | LivingMemory seam + nightly maintenance |
| O26-P2.3 / dormant disposition | `codex-o26-p2-3-dormant-disposition` | #502 | ✅ merged | Codex | Ensemble roster + learning proof + profile extractor parked |
| O26-P2.4 / Product Posture | `codex-o26-p2-4-product-posture` | #503 | ✅ merged | Codex | Settings-backed named posture, wave 1 only |
| O26-P2.5 / Install Smoke Path | `codex-o26-p2-5-install-smoke` | TBD | ⏳ next | Codex | ~30s boot + `/readyz` + faked turn |

Status legend: ⏳ in progress · 🟡 draft PR · 🟢 CI green · ✅ merged · 🔴 conflict

---

## Fișiere blocate (în PR activ)

No active file locks on `main`. The next branch will claim only the P2.5 install-smoke files.

Un fișier blocat nu se atinge de alt agent fără confirmare utilizator.

---

## Ordine de merge (Wave 1 — de venit)

```
Current order:
  1. O26-P2.2 living-memory turn seam + nightly maintenance (#501) ✅
  2. O26-P2.3 dormant-module disposition (#502) ✅
  3. O26-P2.4 Product Posture (#503) ✅
  4. O26-P2.5 Install Smoke Path (next)
```

Next backlog item: **O26-P2.5 Install Smoke Path** now that the wave-1 product posture is merged.

---

## Recomandare — următorul thread (drum spre 1.0)

> Cântărit față de north-star (MOONSHOT §1/§3/§5) și ce s-a livrat în Wave 0 (securitatea H12.1).
> Acum că **1.0 = tot backlogul**, secvențierea contează: alegem ce ridică cel mai mult valoarea pe-misiune.

**Prioritate 1 — H17 Provable Trust (continuă Wave 0).** AgentDojo + AgentHarm ca poartă CI (H17.2, 5 SP) +
dual-LLM / Plan-Then-Execute quarantine pentru conținut tool/web/email (H17.1, 13 SP). Convertește „alternativa
guvernată la OpenClaw" dintr-un *claim* într-un *badge CI verde*; rupe „lethal trifecta" pe agenții email/calendar.
Construiește direct pe SecretStore + skill signing din H12.1.

**Prioritate 2 — H14 Living Memory (cea mai on-mission).** Întâi harness-ul de eval memorie (H14.2, 5 SP, măsoară),
apoi KG bi-temporal (H14.1, 8 SP) + agent de consolidare „sleep-time" cu operații explicite (H14.3, 8 SP).
Generalizează reflecția nocturnă din *rezumă-ziua* în *pre-raționează-pentru-mâine* — chiar sloganul moonshot.

**Apoi:** H13 (plafon capabilitate locală, $0) → H10 competitive edge / H16 (MCP server mode) → H15 computer-use guvernat.

**Temă-flagship transversală:** *sleep-time compute* (H13/H14) + *guvernanță măsurabilă* (H17).

---

## Checklist post-merge (conductor)

### ORIZONT 26 P2.2 — COMPLET

- [x] `main` fetched/rebased from `origin/main`
- [x] Branch created from current main
- [x] Red tests added for default-off seam, enabled turn records, scheduler registration, disabled job no-op
- [x] `_complete_llm_turn()` feeds LivingMemory + decay records when cognition memory is enabled
- [x] `SchedulerService` registers and runs nightly memory maintenance
- [x] `BACKLOG.md` + `STATUS.md` updated from verified scope
- [x] Focused backend verification green
- [x] Ruff / final compile pass
- [x] Branch pushed / PR #501 opened
- [x] GitHub Actions green; PR merged

### ORIZONT 26 P2.3 — COMPLET

- [x] `main` synced after #501 merge
- [x] Branch rebased onto current `origin/main`
- [x] Red tests added for active roster disposition and parked legacy extractor
- [x] PersonaModule + EnsembleModule populated from active agents after `load_agents()`
- [x] Governed learning verified through the autonomy calibration hook
- [x] `profile_extractor.legacy_status()` marks the legacy extractor parked
- [x] `BACKLOG.md` + `STATUS.md` updated from verified scope
- [x] Focused backend verification green
- [x] Ruff / final compile pass
- [x] Branch pushed / PR #502 opened
- [x] GitHub Actions green; PR merged

### ORIZONT 26 P2.4 — COMPLET

- [x] `main` synced after #502 merge
- [x] Branch created from current main
- [x] Design/tests for settings-backed named posture
- [x] Product posture implementation
- [x] `BACKLOG.md` + `STATUS.md` updated from verified scope
- [x] Focused posture/onboarding/security slice green
- [x] Full focused backend verification green
- [x] Branch pushed / PR #503 opened
- [x] GitHub Actions green; PR merged

### ORIZONT 26 P2.5 — URMĂTOR

- [x] `main` synced after #503 merge
- [ ] Branch created from current main
- [ ] Design/tests for install smoke path
- [ ] Install smoke implementation
- [ ] `BACKLOG.md` + `STATUS.md` updated from verified scope
- [ ] Focused backend verification green
- [ ] Branch pushed / PR opened
- [ ] GitHub Actions green; PR merged

### Wave 0 — COMPLET ✅

- [x] `BACKLOG.md` actualizat (H12.1 ✅, H12.9 ✅, H12.10 ✅)
- [x] Test count actualizat în BACKLOG (1184+ passed)
- [x] `docs/SPRINT.md` marcat wave ca ✅ merged
- [x] PR #54 cu toate detaliile pentru PM (deploy instructions, env vars, metrici)
- [x] Branches stale șterse (claude/h12.1-security, claude/h12.10-mute-indicator, claude/h12.9-local-model-ux) — confirmate absente pe origin 2026-06-03

### Wave 1 — PENDING ⏳

- [ ] Wave 1 dispatched (6 agenți în paralel)
- [ ] PR-uri create (draft)
- [ ] CI verde pe toate
- [ ] Merge în ordine (fără conflicte pe BACKLOG.md)
- [ ] BACKLOG.md actualizat

---

## Log sesiune

```
[ORIZONT 25] 2026-07-03 — created `codex-integrate-verified-developments` from `origin/main`
[ORIZONT 25] merged #487 M1.1, #488 M1.2, #489 M2.3, #490 M2.1, #491 status correction locally
[Docs]        BACKLOG/STATUS/ARCHITECTURE/HUD remaining/SPRINT refreshed: M1.1,M1.2,M2.1,M2.3 done; M2.4 partial
[Verify]      backend targeted pytest 22 passed; companion eval gate passed 48/48; py_compile passed with cache redirected
[Verify]      frontend typecheck passed; vitest 155 passed; Playwright Chromium HUD/flow 6 passed after fixing Windows venv path
[Wave 0] H12.1 dispatched (P0 securitate — anti-OpenClaw differentiator)
[Wave 0] H12.10 dispatched (trust indicator HUD)
[Wave 0] H12.9 dispatched (local model UX)
[Wave 0] PR #55 (H12.1) — CI CodeQL 4 findings → fixat → merged
[Wave 0] PR #53 (H12.10) — CI CodeQL false positive → fixat (De Morgan) → merged
[Wave 0] PR #54 (H12.9) — 3 runde conflicte BACKLOG.md → rezolvate; error_logger.py stale → restaurat
[Wave 0] PR #54 merged @ 050f88a — Wave 0 COMPLET
[Wave 0] PR #54 title/body actualizat cu toate detaliile pentru PM
[Wave 1] ⏳ Așteptând confirmare user pentru dispatch
[Docs]   2026-06-03 — formalizat ORIZONT 13–17 în BACKLOG (PR #60)
[Docs]   Decizie: v1.0 = tot backlogul (H10+H11+H12+H13–17); MOONSHOT §4 aliniat
[Docs]   Reconciliate README + GO_LIVE_PLAN + STATUS + gap-analysis-1.0
[Docs]   PR #60 ready for review, CI verde (CI #94 ✅ + CodeQL #72 ✅)
[Docs]   Audit branches: 2 fully-merged (lm-studio-setup, v1.0-release-prep) — ștergere blocată de proxy git
[Next]   Recomandare thread: H17 (trust scorecard) + H14 (living memory) — vezi secțiunea de mai sus
[ORIZONT 26] 2026-07-04 — P0.7 confirmed already done on main; started O26-P1.1 on `codex-o26-p1-1-one-turn-pipeline`
[O26-P1.1] Red tests: plain path lacked runtime truth, stream path lacked persona, completed turns did not nudge affect
[O26-P1.1] Implemented shared Agent prompt wrapper, shared turn enrichment, shared post-LLM record/audit/cognition seam
[Verify]   P1.1/golden chat/stream abort/concurrent stream/chat HTTP/prompt guard/agent integration/token budget/bench/persona/cognition targeted suites green
[PR]       #498 opened, full GitHub Actions green, marked ready for review
[O26-P1.1] #498 independently reviewed (truncation + CDX-7 suspicions cleared, 154 tests re-run on Linux) and MERGED @ 766d15e; e2e path-filter oracle gap -> #499 merged @ 644ace3
[ORIZONT 26] 2026-07-04 — Phase 2 started; O26-P2.1 (AUD-14 env consolidation) claimed on `claude/jarvis-hub-backlog-review-jx87gz`
[O26-P2.1] Workflow inventory: 163 env-read sites / 55 files / 122 vars / EIGHT truthy conventions (not 3) incl. the JARVIS_WORKFLOW_PERSIST=0-enables-the-drain footgun
[O26-P2.1] agents/core/env_config.py (stdlib leaf, one truthy(), unknown->declared-default) + 29 bool sites migrated + ratchet test (red-proved 35 hits); LOCAL_ONLY floor + hardened layering untouched
[ORIZONT 26] 2026-07-04 — main synced at #500; started O26-P2.2 on `codex-o26-p2-2-memory-consolidation`
[O26-P2.2] Red tests: enabled LivingMemory received zero turn records; scheduler had no memory-maintenance registration/body
[O26-P2.2] Implemented default-off LivingMemory turn references at `_complete_llm_turn()` plus decay tracking and 02:40 NREM/REM maintenance with no auto-delete
[Verify]   P2.2/LivingMemory/decay/P1.1/lifespan targeted suites green: 33 passed; STATUS count synced to ~3,584
[O26-P2.2] CodeQL merge blockers addressed: memory-maintenance warnings avoid exception text, completion logging emits counters instead of the whole result payload, and LivingMemory/decay records avoid duplicating raw transcript text
[PR]       #501 opened as draft
[ORIZONT 26] 2026-07-04 — started O26-P2.3 on stacked `codex-o26-p2-3-dormant-disposition` while #501 CI finished
[O26-P2.3] Red tests: active-agent cognition roster was empty; legacy profile extractor had no explicit parked status
[O26-P2.3] Implemented active roster configuration for PersonaModule + EnsembleModule; governed learning proven live at the autonomy calibration hook; profile_extractor parked via legacy_status()
[Verify]   P2.3/ensemble/persona/governed-learning/profile targeted sweep green: 48 passed; STATUS count synced to ~3,588
```

---

## Metrici Wave 0

| Metric | Valoare |
|--------|---------|
| Story Points livrate | 15 SP |
| Teste noi | 45 |
| Total teste (main) | 1184+ passed, 8 skipped |
| PRs merguite | 3 (#53, #54, #55) |
| Buguri rezolvate | BUG-4 (diagnostics.md separat de BACKLOG.md) |
| Timp (estimat) | 1 sesiune |

---

> Template creat: 2026-06-02. Ultima actualizare: 2026-06-03 (docs/roadmap: v1.0 = tot backlogul; next thread = H17 + H14).
