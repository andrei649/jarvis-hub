# SPRINT.md — stare partajată între agenți (sesiune curentă)

> Fișier viu. Actualizat de conductor agent sau lead agent după fiecare wave.
> La start de sesiune: copiază template-ul de mai jos și completează câmpurile.

---

## Sesiune curentă

**Data:** <!-- 2026-MM-DD -->
**Lead agent / Conductor:** <!-- claude / opencode / gemini -->
**Obiectiv sesiune:** <!-- ex: "Dispatch Wave 3 H10 — Workflow Engine Extensions" -->
**Branch de bază:** `main` @ <!-- SHA scurt, ex: `a1b2c3d` -->

---

## Wave-uri active

| Wave | Branch | PR | Status | Agenți | Note |
|------|--------|----|--------|--------|------|
| Wave 1 | `claude/...` | #XX | 🟡 draft / 🟢 green / ✅ merged | agent-name | |
| Wave 2 | `claude/...` | #XX | ⏳ pending CI | agent-name | |

Status legend: ⏳ in progress · 🟡 draft PR · 🟢 CI green · ✅ merged · 🔴 conflict

---

## Fișiere blocate (în PR draft activ)

| Fișier | PR | Agent proprietar |
|--------|-----|-----------------|
| `agents/web.py` | #XX | Wave 1 |
| `workflows/engine.py` | #XX | Wave 2 |

Un fișier blocat nu se atinge de alt agent fără confirmare utilizator.

---

## Ordine de merge (din planul de dispatch)

```
Wave 1 → Wave 2 → Wave 3
       ↘ Wave 4 (după Wave 2)
```

Dependențe stricte: <!-- copiază din docs/plan-*.md secțiunea relevantă -->

---

## Checklist post-merge (conductor)

După fiecare wave mergjuit:
- [ ] `BACKLOG.md` actualizat (✅ pe itemii din PR)
- [ ] Test count actualizat în BACKLOG
- [ ] `docs/SPRINT.md` marcat wave ca ✅ merged
- [ ] Branches stale șterse (sau notate pentru ștergere manuală)
- [ ] Următoarea wave dispatchată (dacă dependențele sunt satisfăcute)

---

## Log sesiune

```
[HH:MM] Wave 1 dispatched — 3 agenți: H10.24, H10.5, H10.8
[HH:MM] PR #XX (H10.24) CI green — merge
[HH:MM] BACKLOG.md actualizat
[HH:MM] Wave 2 dispatched
```

---

> Template creat: 2026-06-02. La fiecare sesiune nouă: resetează câmpurile și începe log curat.
