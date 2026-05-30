# AGENTS.md — instrucțiuni pentru asistenți AI (opencode, Claude, etc.)

## Backlog = sursă unică de adevăr
Când utilizatorul menționează **"backlog"**, **"ce urmează"**, **"next"**, **"priorități"** sau
**"ce lucrez acum"** → **deschide și citește `BACKLOG.md`** înainte de a răspunde, și actualizează-l:
- bifează `[x]` itemii terminați și mută-i în secțiunea **Done** (cu data),
- ideile noi merg în **Icebox**, nu în sprintul activ,
- nu adăuga scope la sprintul curent fără acordul explicit al utilizatorului.

## Context proiect
Sistem personal de 15 agenți AI, 100% local (Ollama), voce + web UI. Solo-dev, <5h/săptămână.
Filozofie: offline-first, privacy (Frigga = strict local). Detalii și strategie: `BACKLOG.md`, `STATUS.md`.

## Convenții
- Cod și docs în română (personalitățile agenților sunt în RO).
- Agenții grei de raționament pot rula pe Claude API (cloud); Frigga rămâne mereu local.
- Nu rula heartbeat-uri sub 60 min cât modelele 32b rulează local (constrângere VRAM 24GB).
