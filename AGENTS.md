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
