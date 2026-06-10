# CLAUDE.md

Instrucțiunile pentru asistenți sunt în **`AGENTS.md`** (sursă unică, partajată cu opencode și Gemini).
Arhitectura e în **`JARVIS.md`**; harta de navigare pentru AI (entry points, lifecycle, index de module,
rețete) e în **`docs/ARCHITECTURE.md`** — începe acolo ca să găsești rapid unde trăiește codul.

**Context mare (Fable 5 / 1M tokens):** `docs/AI_CONTEXT.md` — ce fișiere încarci, în ce ordine,
pe tier-uri și bundle-uri per task, cu estimări de tokeni. Nu încărca repo-ul brut (~2M tokeni).

**Esențial:** când se discută "backlog"/"priorități"/"ce urmează" → citește și actualizează `BACKLOG.md`.
Când se discută "viziune"/"north star"/"moonshot"/"strategie"/"suntem pe drumul bun?" → citește `MOONSHOT.md`
(north star: viziune, principii non-negociabile, phase gates, ritmul de lucru și harta documentelor).
Taskurile care țin **doar de owner** (hardware, GitHub settings, decizii) → `docs/OWNER_TASKS.md`.
