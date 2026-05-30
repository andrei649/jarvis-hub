# Jarvis Hub — BACKLOG & Operations Strategy

> **Reminder permanent (citește-mă de fiecare dată când discutăm "backlog", aici sau în opencode).**
> Acest fișier este sursa unică de adevăr pentru priorități, scop și decizii de realocare a resurselor.
> Reguli pentru orice agent/asistent care lucrează la proiect:
> 1. Când utilizatorul zice "backlog", "ce urmează", "next", "priorități" → deschide și citește acest fișier.
> 2. Când finalizezi un item → bifează-l `[x]`, mută-l în secțiunea **Done** cu data.
> 3. Când apare o idee/feature nou → adaugă-l în **Icebox** (nu în sprintul curent) ca să protejezi focusul.
> 4. Nu adăuga scope la sprintul activ fără acordul explicit al utilizatorului.

---

## Context (snapshot mai 2026)

- **Proiect:** sistem personal de 15 agenți AI, 100% local (Ollama), voce + web UI. v0.2.0.
- **Maturitate:** MVP timpuriu (~2000 LOC, Săpt. 1–3 ✓, Săpt. 4 Polish în curs). Fără teste, fără CI.
- **Resurse:** solo-dev, **< 5h / săptămână**, buget **flexibil dacă merită** (deci cloud API e pe masă).
- **Obiectiv:** TOATE patru direcțiile contează (daily-driver personal + build-in-public + toți 15 agenții + fundație tehnică), dar la <5h/săpt. **trebuie secvențiate**, nu atacate simultan.

---

## 🔴 Bottleneck Analysis — unde se pierde cea mai multă valoare

1. **[CRITIC] Hardware vs. config: toți 15 agenții pe `qwen3:32b` pe un laptop de 24GB VRAM.**
   Un model 32b cuantizat ocupă ~18–22GB → încape **un singur** model în VRAM la un moment dat.
   Heartbeat-urile agresive (Steve la 5 min, Ultron la 15 min) forțează **reload constant** de model
   (cold start de zeci de secunde) → thrashing, latență mare, instabilitate. Acesta e cel mai mare
   consumator de timp/energie raportat la valoare.

2. **[MARE] Zero teste / zero CI.** La <5h/săpt., testarea manuală a fiecărei modificări mănâncă exact
   resursa critică (timpul tău). O regresie prinsă târziu = o seară pierdută.

3. **[MEDIU] Drift de config între surse.** `README.md` (deepseek-r1 + qwen2.5 variate), `agents.yaml`
   (toți qwen3:32b), `STATUS.md` (nume vechi). Fără sursă unică → debugging "de ce nu merge" recurent.

4. **[MEDIU] Scope aspirațional neimplementat:** 10 agenți "bench" (Howard, Bruce, …) fără SOUL.md,
   Neo4j + Qdrant + n8n listate dar nelegate. Creează iluzie de progres și împrăștie atenția.

5. **[MEDIU] Context switching pe 15 agenți × 5 canale** cu <5h/săpt. — prea multe fronturi deschise.

---

## 🟢 Matricea de Realocare a Resurselor

### ⚙️ AUTOMATIZĂM (o dată, beneficiu permanent)
- [ ] **Routing tiered de model** (cel mai mare ROI). Folosește lanțul de fallback existent
      (Claude → Ollama → Bridge): agenții grei de raționament pe **Claude API** (cloud), agenții
      ușori/privați pe **local mic** (qwen2.5:7b). Vezi tabelul de tiering mai jos.
- [ ] **Smoke test minimal + CI pe push** (agent_loader încarcă cei 4 agenți core, router rutează,
      orchestrator întoarce `AgentResponse`). Folosește skill-ul `session-start-hook` pt. web sessions.
- [ ] **Single-source de config model** — un singur loc (agents.yaml) generează ce afișează README/STATUS.

### ✂️ SIMPLIFICĂM (scop redus pentru eficiență)
- [ ] **Reduce agenții activi la 3–4 daily-drivers:** Jarvis (orchestrator), Pepper (EA),
      Friday (brief zilnic), Frigga (family, rămâne 100% local — non-negociabil pentru confidențialitate).
- [ ] **Calmează heartbeat-urile:** nimic sub 60 min cât rulezi local 32b (Steve 5→60, Ultron 15→60).
- [ ] **Îngheață** bench agents, Neo4j, Qdrant, n8n → mută în **Icebox** (nu le ștergem, doar le scoatem din drum).

### 🎯 CONCENTRĂM (timpul tău critic, ce nu poate face nimeni altcineva)
- [ ] **Calitatea prompturilor SOUL.md** pentru cei 3–4 agenți pe care chiar îi folosești zilnic.
- [ ] **UX-ul de voce** (latență wake→răspuns, naturalețe TTS) — asta decide dacă devine daily-driver real.
- [ ] **1 demo "build-in-public"** din ce funcționează deja (voice → Jarvis → răspuns), nu features noi.

### 📊 Tiering recomandat de model
| Tier | Agenți | Backend | De ce |
|------|--------|---------|-------|
| Heavy reasoning | Jarvis, Athena, Stark, Vision | **Claude API** (cloud) | Laptop-ul nu ține 32b stabil; buget flexibil acoperă asta |
| Light / frecvent | Friday, Pepper, Steve, Ultron, Oracle | qwen2.5:7b local | Răspuns rapid, fără reload greu |
| Strict local (privacy) | **Frigga** (family) | qwen2.5:7b/14b local | Date de familie NU pleacă din casă |

---

## 🗺️ Roadmap de Eficiență (ordonat după ROI, calibrat la <5h/săpt.)

- [ ] **Sprint 0 — Stabilitate instant (~1–2h, ROI maxim):** tiering de model + heartbeat-uri ≥60 min.
      Rezultat: latență mică, fără thrashing, sistem pe care chiar îl poți folosi.
- [ ] **Sprint 1 — Single-source config (~1h):** reconciliază README/STATUS/agents.yaml.
- [ ] **Sprint 2 — Plasă de siguranță (~2–3h):** smoke test + CI pe push (session-start-hook).
- [ ] **Sprint 3 — Polish daily-driver (ongoing):** prompturi SOUL pt. 4 agenți + UX voce.
- [ ] **Sprint 4 — Build-in-public (~1h):** un demo scurt din ce merge deja.

## 🎯 Strategia "Lean" — 80% rezultat din 20% efort
**Cele 20%:** tiering de model + 4 agenți activi + heartbeat sanity + smoke test.
**Cele 80% rezultat:** un Jarvis stabil, rapid, pe care îl folosești zilnic — fără să rescrii nimic,
fără teste exhaustive, fără cei 10 bench agents, fără vector DB. Restul devine Icebox până când
daily-driver-ul e solid.

---

## 🧊 Icebox (deferat conștient — NU în sprintul curent)
- Cei 10 bench agents (Howard, Bruce, Wanda, Natasha, Thor, Loki, Heimdall, Apollo, Hermes, Shuri)
- Memorie vectorială reală (Qdrant) + graph (Neo4j)
- Integrare n8n (Oracle)
- Email drafting real (Veronica), calendar conflict resolution real
- Multi-user, observability, rate limiting

---

## ✅ Done
<!-- Mută aici itemii bifați, cu data. Ex: - [x] 2026-05-30 Backlog inițial creat -->
- [x] 2026-05-30 Backlog & strategie de operațiuni inițiale create
