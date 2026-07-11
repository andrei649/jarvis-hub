# CLAUDE.md

Instrucțiunile pentru asistenți sunt în **`AGENTS.md`** (sursă unică, partajată cu opencode și Gemini).
Arhitectura e în **`JARVIS.md`**; harta de navigare pentru AI (entry points, lifecycle, index de module,
rețete) e în **`docs/ARCHITECTURE.md`** — începe acolo ca să găsești rapid unde trăiește codul.

**Context mare (Fable 5 / 1M tokens):** `docs/AI_CONTEXT.md` — ce fișiere încarci, în ce ordine,
pe tier-uri și bundle-uri per task, cu estimări de tokeni. Nu încărca repo-ul brut (~2M tokeni).

**Esențial:** când se discută "backlog"/"priorități"/"ce urmează" → citește și actualizează `BACKLOG.md`
(include secțiunea **Competitive-Gap Roadmap** — cele ~48 teme din planul de produs, cu status DONE/PARTIAL/
SEED/MISSING; analiza de cod e în `docs/research/2026-06-21-roadmap-vs-codebase-audit.md`).
**Întotdeauna când mergi (sau tocmai s-a mergeuit) un PR → reîmprospătează `BACKLOG.md`** în aceeași
mișcare: bifează `✅` itemii livrați + actualizează contorul de teste. De preferat în *același* PR
(înainte de merge); dacă PR-ul e deja mergeuit, fă un commit/PR de catch-up imediat. (Regula completă:
`AGENTS.md` → „BACKLOG sync — în același commit cu merge-ul".)
Când se discută "viziune"/"north star"/"moonshot"/"strategie"/"suntem pe drumul bun?" → citește `MOONSHOT.md`
(north star: viziune, principii non-negociabile, phase gates, ritmul de lucru și harta documentelor).
Când se discută **"AI OS"/piloni de capabilitate/"house brain"/media director/camere/computer operator/
capability registry/"strategia Hermes"/"superior lui Hermes"** → citește `AI_OS_VISION.md` (viziunea
detaliată de capabilități: cei 6 piloni, arhitectura țintă, registry, graduated autonomy, criteriile
S1–S8 vs Hermes; orizonturile ORIZONT 27–33 în `BACKLOG.md`). MOONSHOT.md rămâne north-star-ul scurt.
Taskurile care țin **doar de owner** (hardware, GitHub settings, decizii) → `docs/OWNER_TASKS.md`.
Când se discută **metrici/KPI/măsurarea north-star** (accepted actions, interrupt/reject rate, %-local, p95) → `docs/METRICS.md`
(definiții + endpoint `GET /api/metrics/north-star`). Retrospectiva anuală (status, învățăminte, gap-uri) → `docs/REVIEW_YEAR_ONE.md`.
Materiale de **marketing** (launch, teaser, campanie, brand review, competitive brief) → `marketing/`
(operațional) + `docs/marketing/` (announcement, teaser pack, design brief). Brand: `docs/BRAND_BOOK.md`.
