# The "J.A.R.V.I.S. in the room" build — guide vs. this repo

> Provenance: owner-supplied build guide (2026-08-06) describing the cinematic assistant seen in a
> demo video — a reactive particle sphere, SF data panels, ambient LED sync, a natural voice, and an
> autonomous agent brain wired to real data. This file maps every item in that guide onto what Nerva
> already ships, so nobody rebuilds something that exists.
>
> Related: [VOICE.md](../VOICE.md) (the two voice paths) · [HUD_V2_REMAINING.md](HUD_V2_REMAINING.md)
> (HUD punch-list) · [../ARCHITECTURE.md](../ARCHITECTURE.md) §3 (module index).

## Part 1 — the visual

| Guide item | State in this repo | Where |
|---|---|---|
| Reactive particle sphere ("brain"/plasma orb) | ✅ **shipped by this change** — `VoiceOrb`, a canvas particle sphere bound to the live `useVoice()` state machine (off / standing-by / listening / transcribing / speaking / error). Rendered in cinema mode (`o`), and inline in the voice pill. | `frontend/src/orb.tsx` |
| Three.js / p5.js / GLSL shaders | ➖ **deliberately not used.** The HUD ships as a committed local bundle with no CDN and no runtime asset fetches; the sphere is Canvas-2D projection maths (Fibonacci sphere + yaw/tilt + perspective), so it adds zero dependencies and runs on the same guards as the Neural Mesh. | `frontend/src/orb.tsx` |
| Wallpaper Engine / prebuilt "Jarvis HUD" skins | ➖ not needed — those are wallpapers, not a UI wired to real state. Nerva's own HUD is the surface. | — |
| SF side panels (stats, graphs, figures) | ✅ already far past the guide: the HUD-v3 Console covers every blueprint surface, plus the Decision Inbox, Neural Mesh, ticker, and cinema mode. | `frontend/src/` |
| Home Assistant + a futurist theme as the dashboard | ➖ not the path taken — Nerva has its own HUD; Home Assistant is consumed as a **data/actuation source** by the House Brain (H30), not as the UI. | `agents/core/house/` |
| Big wall screen, black background | ✅ cinema mode (`m` from the HUD) is exactly this: full-bleed, dark, framed for a room. The orb stage (`o`) is the voice-facing half. | `frontend/src/shell.tsx` |
| Ambient LED sync (Hue / Govee / WLED behind the TV) | ❌ **not built.** Nothing in the repo drives a light strip from assistant state. `iot_control.py` / `homebridge.py` are generic device plugins, and H30 actuates Home Assistant devices under approval — neither is an ambient state-colour bridge. Proposed as a separate slice below. | — |

## Part 2 — the functionality

| Guide item | State in this repo |
|---|---|
| Autonomous agent system (LangChain / AutoGPT / CrewAI) | ✅ 17 active agents, orchestrator → router → skills, autonomy queue, approval funnel, Action Kernel mediation. Deeper than the guide: every privileged action is governed, not just executed. |
| Speech-to-text (Whisper / faster-whisper) | ✅ `POST /api/voice/stt`, local faster-whisper; the browser loop VAD-segments an utterance and degrades loudly if STT isn't installed. |
| Text-to-speech, natural voice (ElevenLabs) | ✅ `agents/core/voice/tts.py` supports edge-tts, local XTTS cloning and **ElevenLabs** (`ELEVENLABS_API_KEY`), with sentence-level streaming and a fully-local browser fallback. |
| Google Calendar / Gmail | ✅ `google_calendar.py`, `gmail_plugin.py` plugins. |
| Telegram / Discord bots | ✅ Telegram channel + Safe Comms inbox with governed replies. |
| CRM / database / business figures | ✅ `crm_sync.py`, `meta_ads.py`, `stock_quotes.py`, `analytics.py`, the Signal Layer. |

## What is genuinely missing after this change

1. **Ambient light bridge (proposed).** A default-off plugin that maps assistant state
   (standing-by / listening / thinking / speaking / error) onto a LAN light controller —
   WLED first (plain HTTP JSON on the local network, no cloud account, strict-local by
   construction), Hue/Govee behind their own opt-in. It must reuse the same state source as the
   orb, so the strip and the sphere can never disagree, and stay silent when the device is
   unreachable rather than guessing. Backlog: H23.x (see `BACKLOG.md`).
2. **Owner-side hardware validation.** Wall screen, mic placement and echo-cancellation tuning
   for barge-in are owner-host tasks — see `docs/OWNER_TASKS.md`.
