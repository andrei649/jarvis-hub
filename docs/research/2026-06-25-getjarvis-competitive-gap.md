# GetJarvis Competitive-Gap Analysis — jarvis-hub vs. getjarvis.eu

> Date: 2026-06-25 · Method: live scrape of getjarvis.eu (home / features / connectors / use-cases /
> pricing + the vs-ChatGPT & vs-Claude compare pages) cross-referenced against 2 parallel
> code-exploration passes over `agents/core/plugins/**`, `agents/core/channels/**`, `desktop/`,
> `frontend/`. Owner: Andrei.
> **Status:** analysis — net-new items folded into BACKLOG (themes 0.64–0.66).
>
> Folded into [`BACKLOG.md` → "Competitive-Gap Roadmap"](../../BACKLOG.md#-competitive-gap-roadmap-product-depth).
> Companion: [`2026-06-04-privacy-first-gtm.md`](2026-06-04-privacy-first-gtm.md) ·
> [`2026-06-02-personal-ai-competitors.md`](2026-06-02-personal-ai-competitors.md).

## TL;DR — two different products

`getjarvis.eu` ("Jarvis AI") and our `jarvis-hub` share a name but are **different kinds of product**,
and nearly every gap flows from that. The competitor wins the **last mile** (signature UX, distribution,
SaaS-connector breadth, freemium GTM); we win the **brain** (privacy, governance, agentic depth). None
of their advantages require us to rebuild our core — they are packaging / breadth / go-to-market, most
of which is already seeded in the backlog.

| | **getjarvis.eu** ("Jarvis AI") | **our jarvis-hub** |
|---|---|---|
| Shape | Shipped, monetized **consumer cloud SaaS** + a thin native overlay | **Single-user, self-hosted, local-first agentic OS** (~v0.10–0.11-beta) |
| Privacy story | "EU-hosted, GDPR, AES-256-GCM, no training" — data still uploaded to their cloud | Truly local — data never leaves device/LAN (`LOCAL_ONLY_AGENTS`, on-device VLM) |
| Where the value is | Last-mile UX + distribution + 30 SaaS connectors + freemium funnel | Depth: governance, autonomy, multi-agent, local LLM/VLM |
| Maturity | Polished front door, shallow brain | Deep brain, thin/incomplete front door |

## Competitor profile (grounded from the live site, 2026-06-25)

- **Signature UX** — a small always-on **floating bar** summoned by a **system-wide hotkey** (Cmd+/ on
  Mac, Ctrl+/ on Windows) from any app; double-tap-Control (Alt on Windows) for voice.
- **Screen awareness** — the hotkey "screenshots your current screen and sends it to a multimodal model
  alongside your prompt"; ask about a chart, code snippet, PDF, Figma frame, or email thread with no
  copy-paste. Productized end-to-end.
- **30+ OAuth connectors** — named: Gmail, Slack, Notion, Linear, GitHub, Google Calendar, Drive,
  Sheets, Figma, Asana, Trello, Todoist, ClickUp, Obsidian, Apple apps, Microsoft 365. "Reviewable
  actions" in connected apps (read + small actions).
- **Persistent memory** — tone preferences, project context, recurring patterns across sessions.
- **Cloud model routing** — routes between Claude (3.5 "Flash" / Opus 4.8) and GPT Real Time 2 for
  voice, "based on task complexity"; they hold the keys.
- **Privacy/compliance** — EU-hosted under GDPR, AES-256-GCM token encryption, no training on user data.
- **Platforms** — macOS + Windows (Linux mentioned on the features page).
- **Pricing (freemium)** — Free (15 requests/week + 14-day full Pro trial) · Pro **$16/mo** ($144/yr) ·
  Unlimited **$32/mo** (BYO OpenAI/Anthropic/Google keys, longer context, team features).
- **Marketing funnel** — landing, `/features`, `/connectors`, `/use-cases` (30 use cases × 9
  categories), `/pricing`, `/demo-videos`, `/blog`, comparison pages (`/compare/jarvis-vs-chatgpt`,
  `/compare/jarvis-vs-claude`), SEO landing pages (`/screen-aware-ai-assistant`, `/ai-assistant-for-mac`,
  `/ai-assistant-for-windows`), privacy policy + ToS.

## The gaps, prioritized

Legend — **Verdict:** 🔴 real gap to close · 🟡 partly there · ⚪ strategic non-goal (would conflict with
our local-first / single-user north star).

| # | Gap | Verdict | Evidence in our code | Tracked in BACKLOG? |
|---|-----|---------|----------------------|---------------------|
| 1 | **Floating bar + system-wide hotkey** (the competitor's entire concept) | 🔴 | `frontend/src/app.tsx:714` hotkeys fire only when the browser tab is focused; `desktop/src-tauri/src/main.rs` is a setup stub with no `GlobalShortcutManager`; we ship a browser HUD at `127.0.0.1:8080` | New — **0.64** |
| 2 | **One-hotkey screen-capture → VLM → answer reflex** | 🔴 | VLM brain done (`llm/vlm.py`, theme 0.27 ✅) + `screen_grounding.py` + `desktop_operator.py`, but **nothing wires them** into a capture→answer endpoint or hotkey | New — **0.65** (brain = 0.27) |
| 3 | **Native app + distribution** (download page, signed Mac/Win installers, auto-update) | 🔴 | Tauri v2 **web-wrapper** only (unsigned, v0.9.2); install = `install.sh` / `install.ps1` (venv + pip) | 0.29, 0.57, H23.13 |
| 4 | **SaaS connector breadth** (white-collar suite) | 🟡 | ~20 working integrations, but a messaging/IoT-heavy mix; missing the PM/design/MS/Apple suite (see matrix) | New — **0.66** |
| 5 | **Voice mode productization** (global-hotkey hands-free) | 🟡 | `frontend/src/voice.ts` + `voice/pipeline.py` work **in-browser**; need browser focus, no global-hotkey activation; server pipeline optional/scaffolded | 0.24 |
| 6 | **Frictionless onboarding / free tier / activation** | 🟡 | Config-heavy self-host first-run; onboarding router only indexes local docs; no wizard, no signup, no activation funnel | 0.19, H23.20 |
| 7 | **Frontier-model "quality on tap"** (auto-route, they hold keys) | ⚪→🟡 | Routing tech **already shipped** (`llm/hybrid_router.py`: Claude + Gemini + local auto-escalation); our posture is local-first / BYO-key by design | — |
| 8 | **Monetization & business model** (freemium tiers, billing, team) | ⚪ | None; **single-user by design** (H23.23 = "accept single-user for 1.0"). Closing this means becoming a different company | H23.23 (decision) |
| 9 | **Go-to-market / proof assets** (public site, demos, SEO, comparison pages) | 🔴 | `marketing/` docs only; no public site, no demos, no SEO/comparison pages | 0.52, 0.59, H23.22 |

## Connector matrix

We have **~20 working integrations** — a *different mix* from the competitor's. ~60% coverage of *their*
named list; they have **zero** of our messaging/IoT/OSINT breadth.

| Bucket | Apps |
|--------|------|
| **Have & match** | Gmail · Slack · Notion (write-back) · GitHub · Google Calendar · Google Drive (ingest via rclone) · Spotify |
| **Missing (their named list)** | **Linear · Asana · Trello · Todoist · ClickUp · Figma · Obsidian · Google Sheets · Microsoft 365 (Outlook / OneDrive / full Teams) · Apple Notes / Reminders / Calendar** |
| **We have, they don't** | Telegram · Discord · WhatsApp (local bridge) · Homebridge/HomeKit · Tuya IoT · Apple Health · Twilio SMS · n8n · WorldView 4D OSINT · weather/news · finance (ING/Libra) |

Evidence: `agents/core/plugins/{gmail_plugin,google_calendar,spotify_plugin,crm_sync,oracle_bridge,
whatsapp_bridge,homebridge,n8n,websearch,worldview,signal_layer,balance}.py`,
`agents/core/channels/{slack,telegram,discord,email}.py`, write-back governance in
`agents/core/writeback.py` (Notion/GitHub/Calendar), social in `agents/core/social.py` (X/Twitter),
ingestion in `agents/core/ingestion/drive_sync.py`. The Microsoft side is webhook-only
(`webhook_channels.py`); Todoist is referenced as a write target but not implemented.

## Where we're actually ahead

- **Real privacy / local-first** — their "privacy" still uploads screenshots + app data to an EU cloud.
  Ours: `LOCAL_ONLY_AGENTS`, on-device VLM, LAN-only bridges, a planned network monitor proving zero
  egress. A defensible wedge they structurally can't match.
- **Governance & security depth** — Action Kernel (single mediation point for every privileged action),
  capability tokens, one-tap kill-switch + credential quarantine, tamper-evident audit log, approval
  queues, cross-channel taint-tracking. They advertise *encryption*; we have a *security architecture*.
- **Agentic depth** — multi-agent fleet, missions/workspaces, autonomy + daily digest, subagent gateway,
  workflow runtime, Skills OS, MCP, marketplace. Their product is fundamentally a smart chat bar.
- **Connector types they lack** — messaging (Telegram/Discord/WhatsApp), home/IoT
  (Homebridge/Tuya/Apple Health), SMS, n8n automation, OSINT/WorldView, finance.

## Bottom line + recommended top-3

The competitor wins on the last mile; we win on the brain — and their advantages are packaging/breadth,
most already seeded here. To close the **experiential** distance fastest, in order:

1. **0.64** — global-hotkey floating-bar overlay (the signature UX).
2. **0.65** — wire the existing local VLM into a one-hotkey screen-capture → answer flow.
3. **0.66** — a handful of the missing SaaS connectors (Linear, Google Sheets, Microsoft 365).

Those three neutralize most of the "Jarvis vs ChatGPT/Claude" pitch — on top of a privacy + governance
story they cannot copy.

## Explicit non-goals

These competitor features **conflict with our north star** (local-first, single-user — see
[`MOONSHOT.md`](../../MOONSHOT.md) and H23.23). We win them by *not* doing them:

- **Managed-cloud freemium + billing** — we are self-hosted; there is no account/billing surface to run.
- **Multi-tenant team features** — single-user is an accepted 1.0 posture (H23.23), not a missing feature.
- **Uploading screenshots / app data to a cloud VLM** — the whole privacy wedge is that this stays local.

Treat these as positioning *strengths*, not backlog debt.
