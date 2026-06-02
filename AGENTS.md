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
- **Arhitectură & structură:** `JARVIS.md` (stack, directoare, fluxul orchestrator → router → skills).
- **Specs & planuri (opencode):** `.opencode/plans/*.md` — un spec per skill/modul, scris înainte de implementare (TDD).
- **Workflow paralel:** `PARALLEL_WORKFLOW.md` + `lock.py` (locks la nivel de componentă, evită coliziuni între agenți).

## Rulare & teste
```bash
pip install -r requirements-beta.txt
python -m uvicorn agents.web:app --host 127.0.0.1 --port 8080   # HUD: http://127.0.0.1:8080/
python -m pytest tests/ -v
```
- După modificări JS/CSS: Ctrl+F5 (cache bust). După Python: repornește serverul uvicorn.
- CI rulează `tests/` la fiecare push pe `master` (`.github/workflows/`).
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
Branch de feature per task → PR draft în `master`. Nu împinge direct în `master`.

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

### Pattern conductor agent
Pentru sesiuni cu 3+ wave-uri paralele, desemnează un **conductor agent** dedicat care:
1. Monitorizează CI-ul pe toate PR-urile deschise,
2. Face merge în ordine (respectă dependențele din `docs/plan-*.md`),
3. Actualizează `docs/SPRINT.md` după fiecare wave,
4. Nu scrie cod — doar coordonează și merge-uiește.

Conductor-ul nu se lansează dacă există un singur agent activ.
