# Live-vs-Plumbing Capability Audit (2026-07-18)

> **Why this exists.** The owner observed that the *running* product does much less
> than the merged PRs and docs imply. Six parallel code audits traced every
> capability to its actual actuator to separate what is **LIVE** from what is only
> **PLUMBING** or a **STUB**. This is the durable record; the remediation epic lives
> in [`BACKLOG.md`](../../BACKLOG.md) → "Live-vs-Plumbing Remediation".

## Verdict rubric

| Verdict | Meaning |
|---|---|
| **LIVE** | Produces a real, observable, end-to-end effect in the **default config** (a bare install: no keys, no flags, no hardware) with no missing dependency. |
| **PLUMBING** | The code path is real and wired, but it is off by default, or waits on a key / OAuth / LAN hub / installed engine, or delegates to a "host seam" that is not in the repo. It looks like a feature via the API but changes nothing real. |
| **STUB** | Mock / placeholder / absent: returns canned data, cannot actuate even with credentials, or is persona markdown with zero code. |

## Scoreboard

~77 capabilities audited across 6 domains (judgment tally, not a contract):

- **LIVE ≈ 11** — but only **~3 are user-facing** "does something" features: **weather**, **news**, **local analytics**. The rest are infrastructure (autonomy worker loop, plugin egress gate, learning routing re-ranker, local-model detection/residency #679).
- **PLUMBING ≈ 52** — real, wired, but gated off or waiting on config. Would work once configured; no new code needed.
- **STUB ≈ 14** — mock / placeholder / absent.

**The one-sentence version:** almost every "action" capability **records intent** instead of **doing the thing**, because the real driver is behind an OAuth flow, an API key, a LAN hub (Home Assistant / Frigate / Homebridge), an installed engine (`faster-whisper`, `playwright`), or a feature flag that defaults off. This is *not* vaporware and *not* a bug — the governance, consent, audit, and privacy engineering are real and careful — but the gap between "code-complete / tests pass" and "works when you drive it" is large.

## Domain 1 — Plugins & integrations

| Capability | Verdict | Evidence | To go live |
|---|---|---|---|
| Weather | LIVE | `weather.py:24` real GET `wttr.in`, keyless | — |
| News (RSS) | LIVE* | real RSS; placeholder without `defusedxml` (`news.py:38`) | install `defusedxml` (shipped dep) |
| Analytics (local KPIs) | LIVE | `analytics_store.py:92` real SQLite, `mock=False` | — |
| Email / Gmail | PLUMBING | real API, `raise "Gmail not authenticated"` w/o token | Google OAuth |
| Calendar | PLUMBING | real API, `raise "not authenticated"` w/o token | Google OAuth |
| Stocks / market | PLUMBING | scores only quotes the caller passes; "does not fetch" (`market.py:8`) | a real quotes feed |
| Social / X | PLUMBING | default `NullSocialClient` → deferred; `HttpSocialClient` never built | wire client + `x_api_token` |
| Web search | PLUMBING | Tavily needs key; DDG fallback needs `bs4` (not in requirements) | Tavily key or `beautifulsoup4` |
| Telegram / WhatsApp / Health / Homebridge / Spotify | PLUMBING | each needs token / LAN host / OAuth; blank by default | respective key/host |
| SMS / Twilio | STUB | no creds → `{"status":"mock_sent","sid":"MOCK_SMS_123456"}` | Twilio SID+token |
| CRM / Notion | STUB | no token → `{"status":"mock_saved","id":"MOCK_NOTION_LEAD"}` | Notion token + db id |
| **IoT / Tuya** | **STUB → FIXED** | was: mock toggle + hardcoded `MOCK_SIGNATURE` (401, never actuates). **Now: real Tuya Cloud OpenAPI signing** (this PR); unconfigured → honest degraded result | Tuya client/secret/device id |
| **Bank balance / burn-rate** | **STUB → PARTIALLY FIXED** | `MOCK_BALANCES` default; burn-rate returned `MOCK_BURN_RATE` **even when configured**. **Now: real burn-rate from a transactions CSV** (this PR). Balances still need ING/Libra creds | ING/Libra creds; `gecko_tx_csv_path` for burn-rate |

**Bottom line:** in default config only **weather, news, local analytics** are truly LIVE; everything implying real-world action is credential-gated off or mocked.

## Domain 2 — Computer operator & capability registry (Programs A/B)

| Capability | Verdict | Evidence | To go live |
|---|---|---|---|
| Capability Registry | LIVE* | real **read-only catalog**; never dispatches/executes. `WIRED` label ≠ working feature (`capability_registry.py:417`) | it's a mirror, not an executor |
| Reality-harness governance rails | LIVE | really exercises kill-switch / token-gate / egress / taint, no mock | proves governance, not actuators |
| Browser operator (Playwright) | PLUMBING | real `page.goto/click` code; `playwright` not installed / not in requirements; gated flag off; no `/api/browser/run` route | install playwright + wire an execute route |
| Default browser driver | PLUMBING | `NullBrowserDriver` returns canned `{"ok":True}`; prod callers pass no driver | inject a real driver |
| Desktop operator (Windows) | PLUMBING | real pywinauto/subprocess, Windows-only + not installed → `desktop_dependency_unavailable`; `/api/desktop/run` needs 2 flags, both off | Windows host + pywinauto + flags |
| Operator "pillar" router | PLUMBING | **dead code**: "selects but never executes"; never imported; zero implementations (`operator_router.py:2`) | wire into app + register actuators |
| Reality-harness operator cases | STUB | drive fakes; `promotable:False`, `live_owner_validation:required` | real drivers + a live lane |

## Domain 3 — Media director & camera / vision (Programs C/E)

| Capability | Verdict | Evidence | To go live |
|---|---|---|---|
| Media director `present()` | PLUMBING | default-off flag; `NullMediaDriver` → `no_driver`. "Real actuation is an owner-wired host seam" (`media_director.py:13`) | owner-wired cast/kiosk driver (not in repo) |
| Spotify playback | PLUMBING | real Web API `PUT /me/player/play`; empty token → "Spotify nu e conectat". Closest to live | Spotify OAuth |
| Camera runtime / VLM / ONVIF | PLUMBING | all default-off; need consent + secrets + a LAN **Frigate NVR**; ONVIF needs `wsdiscovery` (absent) | run Frigate + consent + secrets |
| Connect to real cameras | STUB | **no** RTSP/opencv/webcam anywhere; only source is Frigate's HTTP API; frame tests use a synthetic red JPEG | product delegates entirely to Frigate |
| Media generation (image/video) | STUB | `_backends={}` → `backend_unavailable`; cloud path only enqueues approval | inject a diffusion backend |
| `agents/vision`, `agents/argus` | STUB | directories contain only `SOUL.md` / `HEARTBEAT.md` — **zero code** | an actual implementation |

## Domain 4 — House brain, IoT & ambient (Programs D/G)

| Capability | Verdict | Evidence | To go live |
|---|---|---|---|
| House state / control | PLUMBING | no `house` settings seeded → off → `/api/house/state` returns `disabled`, empty | enable flags + LAN Home Assistant + token |
| Home Assistant adapter | PLUMBING | genuinely functional httpx REST + WS subscriber; short-circuits `disabled` unless both env flags set | running HA + flip flags |
| Homebridge client | PLUMBING | real PUT calls (not mocked); default LAN `192.168.1.100`, empty token, not wired to any route | Homebridge host + token + a caller |
| Ambient engine / monitors | PLUMBING | default-off; only prod event source is the camera feed (also off, needs Frigate); house/digital adapters called only in tests | enable ambient + cameras + Frigate |
| IoT / Tuya toggle | STUB → FIXED | `MOCK_SIGNATURE` — couldn't authenticate even credentialed. **Real signing added this PR** | Tuya creds |
| Presence inference | STUB | `PresenceInference.infer` never called in prod (tests only); `presence` always `[]` | a real sensor → evidence → infer pipeline |

## Domain 5 — Action kernel, autonomy, payments & voice

| Capability | Verdict | Evidence | To go live |
|---|---|---|---|
| Autonomy worker loop | LIVE* | really boots + ticks + dispatches approved tasks; but calls Null clients below (`orchestrator.py:785`) | real effect is downstream |
| channel.reply | PLUMBING | the one real sink — `channel_manager.send()`; no channel registered → `channel_manager_unavailable` | configure a channel (e.g. Telegram) |
| writeback / social / call / node execute | PLUMBING | all default to `Null*Client` "host seams" → `{"status":"deferred"}`, no network even on approved tasks | inject `Http*` clients + secrets |
| Action kernel `authorize()` | PLUMBING | returns grant/deny/queue, never executes; default-off `JARVIS_ACTION_KERNEL` | it's a gate; effect is in brokers |
| Payments | PLUMBING | ledger-only by design: "nothing here can actually move money"; `settle()` records "no real rail" (`payments.py:5`) | a real rail adapter (AP2/ACP/x402) |
| Voice STT / TTS | PLUMBING | correct integration, but **zero engines installed** (`faster-whisper`/`edge-tts` commented out) → 503 | install an engine |
| Chat → action | STUB | `handle_input` returns text, never submits a task; agent tool-loop default-off | enable tool loop (then hits Null brokers) |

## Domain 6 — Capability acquisition & learning (Program F)

| Capability | Verdict | Evidence | To go live |
|---|---|---|---|
| Learning routing-health | LIVE | records every turn; re-ranks and drops chronically-failing agents from real data (`orchestrator.py:1292`) | live (bites when ≥2 candidates) |
| LM Studio load / unload | LIVE* | enabled by default; really shells `lms load <model>` (`lmstudio_control.py:176`) | needs LM Studio + `lms` CLI present |
| Model detection / residency | LIVE | real HTTP probe; fail-closes to `unknown`/`offline` (#679 honest) | honest as-is |
| Capability acquisition pillar | PLUMBING | default-off; needs a pinned sandbox image; **no prod path ever creates a promotion proposal** | a real gap→research→generate→propose caller |
| Reflect-and-rewrite (BackgroundReviewer, KC calibration) | PLUMBING | real learn→prompt feedback, but behind the `cognition` master switch (default off); needs a local LLM | flip cognition posture + local LLM |
| Auto model-swap (LRU manager) | PLUMBING | `JARVIS_MODEL_MANAGER` default-off → `ensure_resident` is a no-op | set the flag (GPU-unvalidated) |
| Research→generate→install loop | STUB | only runs in a `live=False` self-benchmark with hardcoded fixtures (`acme_item_parser`) | a real generator, not fixtures |
| Agent skill generation | STUB | generated `main.py` handler returns `"[skill:X] executed — implement logic in handle()"` | actual code synthesis |

## The dominant pattern

**"integration-ready, mock-fallback + host seam."** A capability ships as a real
code path that, when its credential / hardware / engine isn't present, quietly
degrades to a mock payload, a `Null*Client` that returns `"deferred"`, or a
`disabled` status — instead of erroring. Legitimate for building and demoing each
pillar before the whole world is wired, but in a bare install almost none of the
fallbacks are filled in, so what you drive is the scaffold.

**Sharp edge:** when a feature degrades, some paths label it clearly (`balance`
prints "mock data — configure ING/Libra") while others return a quiet
`_mock:true` or a plausible `deferred` that **looks like success**. A user can't
tell a real toggle from a mock one. The fix is to surface capability state
everywhere; the codebase already has the tool (the reality-harness /
capability-registry `state` label), plus the new `plugins/degradation.py` helper
introduced here so mock fallbacks self-report a `_degraded` reason + the config
they need.

## Method

Six parallel code-audit agents, each tracing handlers to their real actuator under
the LIVE/PLUMBING/STUB rubric with file:line evidence, cross-checked against the
running server and an independent dependency probe (missing in the bare sandbox:
`defusedxml, bs4, playwright, pywinauto, cv2, faster_whisper, edge_tts, twilio`).
"Default config" = bare install, no keys/flags/hardware — what the owner tested.
A production deployment with the shipped `requirements.txt` and configured
integrations would move a chunk of the PLUMBING column into LIVE.
