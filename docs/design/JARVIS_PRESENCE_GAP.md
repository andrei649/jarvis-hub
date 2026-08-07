# The "J.A.R.V.I.S. in the room" build — guide vs. this repo

> Provenance, in the order it arrived (2026-08-06): a written build guide → **five frames** of the
> reference video → **two full videos** (a TV build and a phone build). Each pass corrected the one
> before: the guide's "particle sphere" was a text approximation, and the phone video revealed
> controls the stills never showed. The videos are the authority. This file maps every item onto
> what Nerva already ships, so nobody rebuilds what exists.
>
> **What the reference actually is:** a wall-mounted TV in a dark room with blue LED backlight,
> showing a full-bleed *neural firing field* — a dark core surrounded by dense, branching, multi-
> coloured dendrite bundles with long white axon sweeps and a blown-out hot centre — overlaid with
> hairline mono chrome: a letterspaced wordmark, a red `BRIEFING · LIVE` pill, a running clock, four
> stat cards down the sides, a subsystem status rail on the right edge, and the spoken line along
> the bottom. Not a dot sphere: a brain mid-thought.
>
> Related: [VOICE.md](../VOICE.md) (the two voice paths) · [HUD_V2_REMAINING.md](HUD_V2_REMAINING.md)
> (HUD punch-list) · [../ARCHITECTURE.md](../ARCHITECTURE.md) §3 (module index).

## Part 1 — the visual

| Guide item | State in this repo | Where |
|---|---|---|
| Neural firing field (the actual centrepiece) | ✅ **shipped** — `NeuralBurst`: per-tier dendrite trees grown from a deterministic seed, synapse nodes, long white axon sweeps, and a blown-out core, all bound to the live cabinet. Regions are real tiers, node density follows the real agent count, and only tiers that are actually executing fire. | `frontend/src/burst.tsx` |
| The full briefing board (chrome + side cards + status rail + spoken line) | ✅ **shipped** — `BriefingWall`, the `brain` stage of cinema mode (`m` then `b`). | `frontend/src/wall.tsx` |
| Bordered region chips (`190 neurons · firing 0.8%`) | ✅ **shipped** — bordered plate, thick coloured edge bar, region-coloured title, sub-line `N agents · firing X% · N tasks`. The firing share is real (executing ÷ roster), not a decorative percentage. | `frontend/src/burst.tsx` |
| `HOLD TO TALK` round mic control (phone build) | ✅ shipped **in the browser HUD** (native: `H18.25`) — wired to the live `useVoice()` loop: press or hold space starts, release stops. It fails closed for the whole lifecycle: capture needs current `sources.trust` evidence **and** an exact `mic === 'on'`, and it stops on permission loss, trust expiry or unmount. | `frontend/src/wall.tsx` |
| Vertical edge tabs (`AGENT OPS` / `CORTEX`) | ✅ **shipped** as `AGENT OPS` / `CABINET`, carrying live counts; the badge is dropped rather than showing `0` when the feed is unavailable. | `frontend/src/wall.tsx` |
| Portrait phone layout | ✅ shipped **in the browser HUD** — under 820px the cards give way to the edge tabs, the chrome centres and the talk button leads, as in the phone video. The reference's phone build is also a browser on a phone (a Tailscale URL). The **native** iOS/Android apps have none of this: tracked as `H18.25`, and `mobile/PARITY.md` marks the wall ⬜ for native. | `frontend/src/styles.css` |
| Pop-in "spoken point" card (`1.1M+ VIEWS · LAST 30 DAYS`) | ❌ not built — it belongs to a narrated-briefing flow (a card appearing as the assistant speaks each figure). Worth doing once there is a briefing script to drive it; it must pull from real digest data, not a highlight reel. | — |
| Live avatar / camera bubble | ➖ not built — decorative in the reference, and a camera feed on a wall screen is a privacy decision for the owner, not a default. | — |
| Reactive orb (from the written guide, before the frames arrived) | ✅ shipped earlier in the same PR and kept — `VoiceOrb` is a tighter voice-state read than the field, so it stays as the `orb` cinema stage and inline in the voice pill. | `frontend/src/orb.tsx` |
| Three.js / p5.js / GLSL shaders | ➖ **deliberately not used.** The HUD ships as a committed local bundle with no CDN and no runtime asset fetches; both the field and the sphere are Canvas-2D, so they add zero dependencies and run on the same guards as the Neural Mesh. | `frontend/src/burst.tsx`, `orb.tsx` |
| Wallpaper Engine / prebuilt "Jarvis HUD" skins | ➖ not needed — those are wallpapers, not a UI wired to real state. Nerva's own HUD is the surface. | — |
| SF side panels (stats, graphs, figures) | ✅ already far past the guide: the HUD-v3 Console covers every blueprint surface, plus the Decision Inbox, Neural Mesh, ticker, and cinema mode. | `frontend/src/` |
| Home Assistant + a futurist theme as the dashboard | ➖ not the path taken — Nerva has its own HUD; Home Assistant is consumed as a **data/actuation source** by the House Brain (H30), not as the UI. | `agents/core/house/` |
| Big wall screen, black background | ✅ cinema mode (`m` from the HUD), with three stages: `n` mesh (who is working), `o` orb (voice state), `b` the briefing wall (the reference layout). | `frontend/src/shell.tsx` |
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

## The one place we deliberately diverge from the reference

The reference's cards show a marketing agency's KPIs — leads found, cold emails drafted, ad spend,
MRR. Nerva has no such numbers, and inventing plausible ones onto a wall screen is exactly the
failure this codebase is built to avoid. The same card slots therefore carry figures this hub can
prove: roster size, agents executing, tasks running/waiting, measured %-on-device, the resident
local model, whether a cloud lane was reported, decisions pending, and a subsystem status rail
(server, model, mic, STT, TTS, strict-local, task feed). Anything unmeasured renders `—` with the
reason in its `title` — see `wl-miss` in `wall.tsx` and the test that pins it.

## What is genuinely missing after this change

1. **Ambient light bridge (proposed).** A default-off plugin that maps assistant state
   (standing-by / listening / thinking / speaking / error) onto a LAN light controller —
   WLED first (plain HTTP JSON on the local network, no cloud account, strict-local by
   construction), Hue/Govee behind their own opt-in. It must reuse the same state source as the
   orb, so the strip and the sphere can never disagree, and stay silent when the device is
   unreachable rather than guessing. Backlog: H23.x (see `BACKLOG.md`).
2. **Owner-side hardware validation — the wall is unproven in a room.** Everything here was
   verified in a headless browser against reference frames. Legibility at viewing distance, mic
   pickup from across the room, echo when the reply plays through the TV, and the per-room privacy
   call on the spoken line are tracked as an explicit owner task ("Wall-screen room validation")
   in `docs/OWNER_TASKS.md`. Release readiness stays false until that is done.
