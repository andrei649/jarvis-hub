# SPRINT.md — stare partajată între agenți (sesiune curentă)

> Fișier viu. Actualizat de conductor agent sau lead agent după fiecare wave.
> La start de sesiune: copiază template-ul de mai jos și completează câmpurile.

---

## Sesiune curentă

**Data:** 2026-07-03 (ORIZONT 25 M1/M2 integration)
**Lead agent / Conductor:** Codex
**Obiectiv sesiune:** integrate verified Codex developments toward `main`, then update docs with done vs WIP truth.
**Branch:** `codex-integrate-verified-developments` (local integration branch; source draft PRs #487–#491)

**Scope decision (2026-07-03):** integrate the already-reviewed local Codex branches in dependency order
instead of widening backlog scope. M1.1/M1.2/M2.1/M2.3 are treated as verified done once the combined
targeted suite passes; M2.4 remains **partial** until baseline persistence/live runner exists.

**Previous session:** ORIZONT 25 current-batch stabilization (`main` @ `e1f1de8`) plus one corrective
status PR (#491) documenting the six-item batch as a protocol exception.

---

## Wave-uri active

| Wave | Branch | PR | Status | Agenți | Note |
|------|--------|----|--------|--------|------|
| M1.1 / K3 budget unification | `codex-m1-1-k3-budget-unification` | #487 | ✅ integrated locally | Codex | Shared `BudgetLedger` dimensions + handler token hook |
| M1.2 / Action origin threading | `codex-m1-2-action-origin-threading` | #488 | ✅ integrated locally | Codex | Inbound channels bind `Action.origin="inbound"` |
| M2.3 / OpenAPI type truth | `codex-m2-3-openapi-ts-typegen` | #489 | ✅ integrated locally | Codex | Generated TS schema + CI diff gate |
| M2.1 / Flow E2E | `codex-m2-1-flow-e2e` | #490 | ✅ integrated locally | Codex | Chat SSE/stop + voice PTT Playwright specs |
| Status correction | `codex-batch-status-corrections` | #491 | ✅ integrated locally | Codex | M2.4 downgraded to partial; protocol exception recorded |

Status legend: ⏳ in progress · 🟡 draft PR · 🟢 CI green · ✅ merged · 🔴 conflict

---

## Fișiere blocate (în PR draft activ)

`codex-integrate-verified-developments` temporarily owns the files touched by #487–#491 until the
integration PR lands. The source draft PRs should be treated as superseded by this integration pass.

Un fișier blocat nu se atinge de alt agent fără confirmare utilizator.

---

## Ordine de merge (Wave 1 — de venit)

```
Executed order:
  1. M1.1 K3 budget unification
  2. M1.2 Action.origin threading
  3. M2.3 OpenAPI -> TS typegen/diff gate
  4. M2.1 chat/voice flow E2E
  5. Status correction / M2.4 honesty note
```

Next backlog item after this integration lands: **M3.1 mobile approval queue** unless the owner chooses
to finish M2.4 persistence/live-runner first.

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

### ORIZONT 25 integration — ÎN CURS

- [x] `main` fetched and integration branch created from `origin/main`
- [x] Source branches #487–#491 merged locally in dependency order
- [x] `BACKLOG.md` reconciled: M1.1/M1.2/M2.1/M2.3 ✅, M2.4 🟡 partial
- [x] `STATUS.md`, `docs/ARCHITECTURE.md`, `docs/design/HUD_V2_REMAINING.md` updated from verified scope
- [x] Combined targeted verification complete
- [ ] Integration branch pushed / PR opened or protected-main path completed

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
