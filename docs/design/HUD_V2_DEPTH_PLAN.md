# HUD v2 — Depth grinding plan

> The execution plan for the remaining HUD v2 depth (after P0–P6 shipped + the LIVE/SEED + CI‑build‑guard +
> settings‑editor follow‑ups). Source punch‑list: `HUD_V2_REMAINING.md`. Each batch = one green PR behind the
> **parity gate** (`tests/test_hud_v2_parity.py`) + the **`hud-v2-build`** CI job. Generated 2026‑06‑05.

## Sequencing (recommended top‑to‑bottom)

### Batch B — finish the Console editors  ·  *low risk, high value*  ·  **(in progress — settings editor ✅)**
- **Prompt versions** → A/B + diff + rollback + commit + preview (`/api/admin/prompts/{id}/{history,version/{n},diff,commit,rollback,ab,preview}`).
- **Data Spaces** → create / assign / unassign / delete CRUD (`/api/memory/spaces*`).
- **Secrets** → add a store form (`POST /api/secrets/broker`). **Capabilities** → grants list + check.
- **Rooms** → create + open history + send with `@mentions` (`/api/rooms*`).

### Batch D‑lite — small signature wins  ·  *low risk*
- **Strict‑local / mic top‑bar badge** (`/api/trust/status`). **Per‑message TTS** (🔊 → `/tts`) + **browser mic**.
  Network **task‑fan** from live `/tasks`.

### Batch C — wire the still‑mock modes  ·  *medium risk (shape mapping — verify against a live run)*
- Build (workflow DAG / skills / sandbox), Comms (live threads + **Discord/Slack**), Memory (recall / decay /
  KG live), Trust (capability grants + real %‑local), Autonomy (AUTO/ASK/OFF policies), Dossier (soul +
  run‑history). Finance/Health/Knowledge/Family need their plugins configured.

### Batch G — small backend additions  ·  *unblocks C/D*
- Streaming cognition SSE (`/api/cognition/stream`) + provenance on the chat stream; a `%‑local`/locality
  summary endpoint (compose from `/api/analytics/model-tiers` + `/api/cost`).

### Batch E — settings & prefs UI  ·  *low risk*
- In‑app settings menu so **look / density / motion / scanline / dotgrid** are user‑changeable + persisted
  (today only accent + language persist).

### Batch F — toolchain  ·  *low risk, ongoing*
- Generate TS types from `/openapi.json` (`openapi-typescript`) → drop `@ts-nocheck` incrementally; **self‑host
  fonts** (Space Grotesk + JetBrains Mono woff2).

### Batch A — runtime verification *(needs the owner)* → Batch H — cutover *(when verified)*
- Owner runs `/v2`, flags mismatches; then flip default `/` → v2 (`JARVIS_HUD=v2` or hardcode), archive the old
  HUD, update `README` / `STATUS.md` / `JARVIS.md`.

## Order recommendation
**B + D‑lite** first (safe, visible) → **C** (after a live run‑through so shapes are mapped against reality) →
**E / F / G** → **H**. Roughly 5–6 PRs. The parity gate already guarantees coverage; this is all *depth*.
