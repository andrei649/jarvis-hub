---
name: jarvis-load-context
description: Use FIRST, before reading source, when starting any task in the jarvis hub repo — to load the right files instead of the ~2M-token raw repo. Triggers at the start of backend, frontend, voice, security, WorldView, or marketing work, or when unsure "what should I read".
---

# Which context to load (don't load the repo raw)

The repo is **~2M tokens** — never load it all. Load **Tier 0 + Tier 1** (~75K), then **one** task bundle. Full map: `docs/AI_CONTEXT.md`.

**Tier 0 (always, ~25K), in order:** `CLAUDE.md` → `AGENTS.md` → `docs/ARCHITECTURE.md` → `MOONSHOT.md` → `STATUS.md` → `README.md` → `JARVIS.md`.

**Tier 1 (planning/backlog):** `BACKLOG.md` (header + the section you touch — it's THE priority truth) + `GO_LIVE_PLAN.md`.

**Then add exactly one bundle:**
| Task | Load |
|------|------|
| Backend | touched `agents/core/<module>` + `agents/web.py` or `routers/*` + matching `tests/test_*` (use ARCHITECTURE §3 module index to pick) |
| Frontend / HUD | `frontend/src/**` + design docs + `tests/test_hud_v2_parity.py` |
| Voice | `docs/VOICE.md` + `agents/core/voice/**` + `frontend/src/voice.ts` |
| Security | `agents/core/security/**` + `docs/AUDIT.md` + `SECURITY.md` |
| WorldView | `worldview/README.md` + `docs/contracts/worldview-bridge.md` (only coupling) |

When docs disagree, **BACKLOG wins**; fix the stale one.
