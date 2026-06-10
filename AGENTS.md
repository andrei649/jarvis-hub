# AGENTS.md — instrucțiuni partajate pentru asistenți AI (opencode, Claude, Gemini, Antigravity)

Sursă unică de convenții, citită de toți asistenții care lucrează la Jarvis Hub.

> **Lucru în paralel / coordonare între agenți:** `PARALLEL_WORKFLOW.md` + `lock.py`
> (cunoaște `opencode`, `claude`, `antigravity`). Onboarding Antigravity: `docs/handoff-antigravity.md`.

## Backlog = sursă unică de adevăr pentru priorități
Când utilizatorul menționează **"backlog"**, **"ce urmează"**, **"next"**, **"priorități"** sau
**"ce lucrez acum"** → **deschide și citește `BACKLOG.md`** înainte de a răspunde, apoi actualizează-l:
- bifează `✅` itemii terminați (story sub formatul `H#.#`/`S#.#`, cu S = story points, P = prioritate),
- lucrările blocate pe infra externă se marchează `🔴` cu dependența explicită,
- nu adăuga scope la sprintul activ fără acordul explicit al utilizatorului.

## Hărți de orientare
- **Navigare pentru AI (începe aici):** `docs/ARCHITECTURE.md` — entry points, request lifecycle, index de module, rețete „cum adaug X". Optimizat să găsești rapid unde trăiește codul, fără a citi tot.
- **Context mare (1M tokens):** `docs/AI_CONTEXT.md` — tier-uri de încărcare + bundle-uri per task cu estimări de tokeni; nu încărca repo-ul brut.
- **Arhitectură & structură:** `JARVIS.md` (stack, directoare, fluxul orchestrator → router → skills).
- **Taskuri owner-only:** `docs/OWNER_TASKS.md` — hardware/GitHub-settings/decizii; nu le bloca pe agenți, marchează-le acolo.
- **Specs & planuri (opencode):** `.opencode/plans/*.md` — un spec per skill/modul, scris înainte de implementare (TDD).
- **Workflow paralel:** `PARALLEL_WORKFLOW.md` + `lock.py` (locks la nivel de componentă, evită coliziuni între agenți).

## Rulare & teste
```bash
pip install -r requirements-beta.txt
python -m uvicorn agents.web:app --host 127.0.0.1 --port 8080   # HUD: http://127.0.0.1:8080/
python -m pytest tests/ -v
```
- După modificări JS/CSS: Ctrl+F5 (cache bust). După Python: repornește serverul uvicorn.
- CI rulează `tests/` la fiecare push pe `main` (`.github/workflows/`).
- **Code health (caută îmbunătățiri):** `pip install -r requirements-dev.txt` apoi
  `python scripts/code_health.py` — lint + format + dead-code + complexitate, dintr-o
  singură comandă. Config în `pyproject.toml`. **Advisory, nu blochează** (rulează și în
  CI: `.github/workflows/code-health.yml`). Rezolvă findings **în fișierele pe care deja
  le atingi**, nu în sweep-uri pe tot repo-ul. `--fix` aplică autofix-urile sigure.

## Convenții (non-negociabile)
- **Local-first.** Stack pur Python 3.12 + FastAPI + LM Studio/Ollama. Cloud-ul e opt-in, per-agent.
- **Agenți strict-local** (`LOCAL_ONLY_AGENTS` în `agents/core/llm/hybrid_router.py`): **frigga, ultron, howard**
  — niciun apel extern, niciun fallback cloud. Frigga ține datele de familie pe LAN, mereu.
- **Agenți cloud-only:** athena. Restul: routing `auto` (grei → Claude/Gemini, ușori → local).
- **Skills:** pattern loader în `skills/<name>/{SKILL.md,main.py}`, descoperite de `agents/core/skills/loader.py`.
- **Limbă:** docs și personalitățile agenților (`agents/*/SOUL.md`) sunt în RO/EN după context; nu schimba tonul unui agent fără acordul utilizatorului.

## Stil de lucru
Verde devreme peste perfecțiune · teste peste documentație · livrare peste analiză.
Branch de feature per task → PR draft în `main`. Nu împinge direct în `main`.

## Coordonare multi-agent (reguli non-negociabile)

### Rebase-first — obligatoriu la start
La începutul oricărui task, primul lucru pe care îl faci:
```bash
git fetch origin
git rebase origin/main
```
Nu sări peste acest pas. Un agent care pornește din main vechi generează conflicte garantate.

### Draft PR = blocat pentru alți agenți
Un PR în stare **draft** (indiferent dacă e al tău sau al altui agent) este **read-only** pentru oricine altcineva.
- Nu modifica fișiere atinse de un PR draft deschis fără confirmare explicită din partea utilizatorului.
- Dacă ai nevoie de un fișier blocat, așteaptă merge-ul sau discută cu lead agent-ul sesiunii.
- **Un singur lead agent per sesiune.** Lead agent-ul coordonează wave-urile și face merge-urile.

### BACKLOG sync — în același commit cu merge-ul
Agentul care face merge (sau imediat după) actualizează `BACKLOG.md`:
- bifează `✅` itemii din PR-ul mergjuit,
- actualizează contorul de teste dacă s-au adăugat,
- nu deschide un PR separat doar pentru BACKLOG — include actualizarea în PR-ul de feature sau într-un commit direct pe main după squash merge.

### Bridge browser↔mobil — paritate sincronizată
HUD-ul browser și app-urile native iOS/Android (`mobile/`) consumă **același API** (`agents/web.py`).
Ca dezvoltările pe browser să nu lase mobilul în urmă în tăcere, când un PR adaugă/schimbă un
**endpoint user-facing sau o capabilitate HUD**, în *același* PR:
- actualizează registrul de paritate [`mobile/PARITY.md`](mobile/PARITY.md) (rândul suprafeței: browser ✅, starea mobil),
- dacă mobilul rămâne în urmă, deschide/actualizează un task de paritate `H18.x` în `BACKLOG.md` (ORIZONT 18).

Astfel orice feature de browser devine automat un task pe iOS/Android. Suprafețele intenționat
desktop-only se marchează `➖` în ledger, cu motivul notat. Menținerea ledgerului = `H18.10` (umbrelă mereu deschisă).

### Backend↔HUD — aceeași regulă pentru cockpit-ul V2
Gate-ul de *coverage* (`tests/test_hud_v2_parity.py`) clasifică fiecare rută, dar nu garantează
**controale UI** (audit 2026-06-10: backendul a luat-o înainte cu ~37 endpoint-uri — vezi `TASK-2`
în `BACKLOG.md`). De aceea, când un PR adaugă/schimbă un **endpoint user-facing**, în *același* PR:
- ori adaugi/wirezi suprafața în HUD V2 (`frontend/src/`),
- ori adaugi endpoint-ul explicit în punch-list-ul `docs/design/HUD_V2_REMAINING.md` (+ rândul TASK-2
  din `BACKLOG.md` dacă schimbă scopul). Endpoint-urile machine-facing se marchează `NOT_IN_HUD`
  în gate-ul de paritate, cu motivul notat.

### Pattern conductor agent
Pentru sesiuni cu 3+ wave-uri paralele, desemnează un **conductor agent** dedicat care:
1. Monitorizează CI-ul pe toate PR-urile deschise,
2. Face merge în ordine (respectă dependențele din `docs/plan-*.md`),
3. Actualizează `docs/SPRINT.md` după fiecare wave,
4. Nu scrie cod — doar coordonează și merge-uiește.

Conductor-ul nu se lansează dacă există un singur agent activ.
