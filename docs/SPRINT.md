# SPRINT.md — stare partajată între agenți (sesiune curentă)

> Fișier viu. Actualizat de conductor agent sau lead agent după fiecare wave.
> La start de sesiune: copiază template-ul de mai jos și completează câmpurile.

---

## Sesiune curentă

**Data:** 2026-06-03 (sesiune docs/roadmap)
**Lead agent / Conductor:** claude
**Obiectiv sesiune:** formalizare ORIZONT 13–17 + reconciliere docs roadmap (PR #60)
**Branch:** `claude/project-status-report-rosXA` (PR #60, ready for review, CI verde)

**Decizie de scope (2026-06-03):** **v1.0.0 = tot backlogul terminat** — H10 + H11 + H12 + H13–H17.
Frontierele H13–17 sunt formalizate în BACKLOG + MOONSHOT §4; docs reconciliate (README, GO_LIVE_PLAN, STATUS,
gap-analysis). Fără grabă pe tag, dar nimic nu se sare din gate.

**Sesiune anterioară:** Wave 0 H12 — Securitate P0 + trust indicator + local model UX (`main` @ `050f88a`).

---

## Wave-uri active

| Wave | Branch | PR | Status | Agenți | Note |
|------|--------|----|--------|--------|------|
| Wave 0 / H12.1 | `claude/h12.1-security` | #55 | ✅ merged | agent-a49c480c3b715fddb | P0 securitate: SecretStore + skill signing + approval split |
| Wave 0 / H12.10 | `claude/h12.10-mute-indicator` | #53 | ✅ merged | agent-a526fc8bd13e13073 | TrustIndicator HUD (mic + strict-local chips) |
| Wave 0 / H12.9 | `claude/h12.9-local-model-ux` | #54 | ✅ merged | agent-a227a1aaab3eda740 | Local model browse/switch (LM Studio + Ollama) |

Status legend: ⏳ in progress · 🟡 draft PR · 🟢 CI green · ✅ merged · 🔴 conflict

---

## Fișiere blocate (în PR draft activ)

_Niciun PR draft activ. Wave 1 neînceput._

Un fișier blocat nu se atinge de alt agent fără confirmare utilizator.

---

## Ordine de merge (Wave 1 — de venit)

```
Wave 1 (6 agenți, ~27 SP):
  H10.24 Cost per Trace (5 SP)
  H9.3b  Dataset Regression (5 SP)
  H10.5  MCP Server Mode (8 SP)
  H10.8  Inbound Webhooks (3 SP)
  H12.2  Onboarding drop-folder (3 SP)
  H12.4  Wyoming protocol (5 SP)
```

Dependențe Wave 1: toate independente față de Wave 0 (pot rula în paralel).
Merge order recomandat: H12.2 → H12.4 → H10.24 → H9.3b → H10.8 → H10.5

> Wave 1 e încă valid (P1/P2, independent), dar vezi recomandarea de mai jos: dacă deschidem un thread nou
> de valoare mai mare, **H17 + H14** întrec ca prioritate items-ele de observabilitate din Wave 1.

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
