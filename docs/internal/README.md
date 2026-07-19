# docs/internal — archived working material (provenance, not documentation)

> Everything here is **historical scratch**: one-shot session prompts, superseded snapshots,
> and design handoffs that shaped the project but are no longer sources of truth. Nothing in
> this directory should be loaded for current work (see [`docs/AI_CONTEXT.md`](../AI_CONTEXT.md))
> or treated as accurate about the present codebase. Moved here from the repo root 2026-06-10.

| Item | What it is | Superseded by |
|------|-----------|---------------|
| `claude_batch_prompt.md` | One-shot "PM AI" session prompt (RO) used to drive a ~700K-token batch implementation run over the backlog | `BACKLOG.md` + `AGENTS.md` workflow |
| `gemini_architecture_prompt.md` | Architecture briefing written for a Gemini review session (v0.2.x era); its TODOs seeded TASK-1 (Howard backend) | `docs/ARCHITECTURE.md` |
| `PROMPTURI_FEATURES.md` | Ready-to-paste feature prompts (RO, 2026-05-30, targeting 0.2.1→0.3.0) — those features shipped long ago | `BACKLOG.md` (H-items, all ✅) |
| `DOCUMENTATIE_EXHAUSTIVA.md` | Exhaustive system documentation snapshot of v0.2.1 (RO, 2026-05-30) | `docs/ARCHITECTURE.md` + `NERVA.md` |
| `ANALIZA_CRITICA.md` | Critical system analysis of v0.2.1 (RO, 2026-05-30) | `docs/2026-06-10-full-project-analysis.md` |
| `design_handoff_jarvis_hub/` | The HUD design-session handoff: v0.3 prototype (`design/`, `pr-hud-v2/`), OPENCODE prompt, backend snippets — the prior art the HUD V2 program was built from | `frontend/src/` (shipped HUD V2) + `docs/design/HUD_V2_*.md` |

**Conventions:** nothing here gets updated — if a fact in these files is wrong *today*, that's
expected; they are snapshots. New working material of this kind goes to `.opencode/plans/`
(specs) or gets a dated `docs/YYYY-MM-DD-*.md` report instead of landing in the repo root.
