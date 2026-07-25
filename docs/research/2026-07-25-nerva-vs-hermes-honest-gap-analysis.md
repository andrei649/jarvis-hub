# Nerva (jarvis-hub) vs Hermes Agent — honest gap analysis (2026-07-25)

> **Immutable dated research doc** (per `docs/AI_CONTEXT.md`). Do not "fix" it later; write a new
> dated file when reality moves. Re-grounds [`2026-06-07-hermes-agent.md`](2026-06-07-hermes-agent.md)
> (Hermes at v0.16.0, 185.7k★), [`2026-07-06-hermes-agent-migration-plan.md`](2026-07-06-hermes-agent-migration-plan.md)
> and the Hermes verdict in [`NERVA_VISION.md`](../../NERVA_VISION.md) §8.
>
> **Revision note (same day, pre-merge).** The first draft of this file was put through an
> 11-agent adversarial verification pass: six refuters (one per claim cluster, instructed to
> disprove) and five deepening passes on dimensions the draft skipped. **103 claims audited: 46
> confirmed, 56 refuted or partial, 16 story-changing.** This is the corrected text. The draft's
> own errors are listed in §9 rather than quietly deleted — the errors ran in *both* directions,
> and that is itself a finding about how this repo talks about itself.
>
> **Method.** Hermes side: live fetches of the GitHub repo page, the releases page and the official
> docs (toolsets, browser, computer-use, memory, skills, security, profiles, messaging, providers,
> installation) on 2026-07-25, plus two public GitHub issues. **Everything on the Hermes side is a
> vendor claim** — Hermes's docs describing Hermes — not code-audited by us; that asymmetry is
> flagged wherever it matters. Nerva side: this working tree at `06cf011`, traced to file:line, with
> BACKLOG ticks treated as claims to check rather than evidence.

---

## 0. The one-paragraph answer

Nerva is **architecturally ahead and operationally behind**, and both halves of that sentence are
more extreme than the repo's documents admit. Hermes is a shipped product — 220.1k★, 41.9k forks,
v0.19.0 on 2026-07-20, ~3,300 issues closed in that release alone — with real browser and desktop
actuation, ~26 messaging surfaces, 300+ models, a one-line installer that provisions its own
runtime, and a memory/learning loop that is **on by default**. Nerva has a genuinely better
architecture for the thing we say we want to build, ~100k lines of backend and 5,406 backend tests
behind it, and four capability pillars Hermes does not attempt at all. But: in the shipped default
posture our learning loop is off *even in the "Design Partner" posture designed to turn the
intelligence layer on*; our memory silently forgets across restarts because of a bug in the
**always-on** path, not a flag; our only live approval surface (Telegram) has **no owner binding**;
our action-level audit sink is `None` in production; and the "superior to Hermes" bar has never
been measured against Hermes, on any axis, once. Meanwhile the strategic fact the first draft
missed entirely: this repo is **public**, has been marketed to ~24,000 people, and converted
**zero** design partners. The binding constraint is not capability. It is that nobody can get to
first value.

---

## 1. Scoreboard

Corrected against source. Hermes cells are vendor claims fetched 2026-07-25.

| Dimension | Hermes | Nerva (`06cf011`) | Who leads |
|---|---|---|---|
| Distribution | 220.1k★ · 41.9k forks · 840 watchers · public product | **public** repo, 4★ / 1 fork / 979 commits; ~24k people reached by one campaign → **0 design partners** | **Hermes, categorically** |
| Release cadence | v0.17 (06-19) → v0.18 (07-01, 949 issues closed, entire P0/P1 backlog) → v0.19 (07-20, ~3,300 issues, ~1,065 PRs) | v0.11.0; 1.0 behind 9 open owner gates | **Hermes** |
| Browser actuation | 6 backends (local Chromium, CDP attach, Camofox, Browserbase, Browser Use, Firecrawl). **Opt-in** — toolset must be enabled and a backend reachable | driver exists (`browser_playwright.py`), **no execution route at all** — the two prod call sites only `preview()`; `playwright` in zero requirements files | **Hermes** |
| Desktop actuation | `cua-driver` over MCP, mac/win/linux, background, a11y+screenshots, destructive actions require approval. **Off by default** (`hermes computer-use install`) | **fully wired chain** `/api/desktop/run` → gated ToolRPC → Action Kernel → real `WindowsDesktopDriver`; blocked by 2 env flags + missing `pywinauto` + empty `app_launchers` (every `launch` → `app_not_allowlisted`) | **Hermes** (both opt-in; theirs is one documented command) |
| Exec targets | 6 working backends (local, docker, ssh, modal, daytona, singularity) | 3 declared *profiles* + per-target policy and hash-chained authorization audit — but `environments/` is a **policy plane that never executes**, and **no SSH transport exists in the repo** (no paramiko/asyncssh/fabric anywhere) | **Hermes on execution**, Nerva on the audit idea |
| Providers | 300+ models; Portal/OpenRouter/Vertex/Fireworks/DeepInfra + first-class local (Ollama/vLLM/LM Studio) | 6 declarative `ProviderProfile`s (metadata only, no routing) over 6 implemented backends + LM Studio control + residency detection | **Hermes** |
| Channels | ~26 surfaces (Telegram, Discord+VC, Slack, WhatsApp ×2, Signal, SMS, iMessage, Matrix, Teams, LINE, IRC, ntfy, HA, Raft, …) | **11 adapters**: web SSE, Telegram, Discord, Slack, email, voice + WhatsApp/Signal/Matrix/Teams/Google Chat over the governed webhook family (**config-only, no extra SDK**) | **Hermes**, but by ~2.4×, not the 4× the draft implied |
| Memory & learning loop | background review **on by default**, `write_approval: false`; bounded `MEMORY.md`/`USER.md` injected every session with usage %; FTS5 session search; `/learn`, `/journey` | mechanism fully ported — and gated by **five** conditions; `cognition.review_enabled` is **omitted from `WAVE1_FLAGS`**, so the Design-Partner posture still yields no learning loop. Default install = 6-turn prompt window + 100-turn ring | **Hermes, categorically** |
| Voice | Voice Mode on CLI/TUI/Telegram/Discord+VC; local faster-whisper + free Edge TTS, no keys (opt-in extras) | **no engine installed by any install path** (all commented out, absent from the PyInstaller bundle); HUD mic *refuses to start*; `/tts`,`/stt` → 503 | **Hermes** |
| Home Assistant | 4 `ha_*` tools auto-enabled by `HASS_TOKEN`; 6 dangerous domains blocked; HA as **event gateway** (WS `state_changed` in, notifications out). **No approval gating on `ha_call_service`** | real REST+WS adapter; needs 2 env flags + SecretBroker token handle + URL + LAN allowlist + reachable HA. Kernel-mediated when on | **Hermes today**; Nerva on governance |
| House model | `area` name filter over HA entities; per-family-member **profile isolation** (deployment answer, not a permission model) | room/device graph, contracts, per-person authority, private store — **but `/api/house/state.presence` is structurally always `[]`**: the only writer of those predicates has no production caller | **Nerva on design, nobody on delivery** |
| Cameras | none | 4.5k LOC: consent leases, Frigate read-only, event vault, deterministic (model-free) retrieval; ONVIF leg needs undeclared `wsdiscovery`; VLM leg needs a self-hosted VLM server | **Nerva** (needs LAN Frigate) |
| Media | image gen, TTS, vision | `present()` + 878 LOC — **no `MediaDriver` implementation ships and the HTTP construction site has no injection point**. Not config-gated: driver-missing | **Nerva on design, unreachable in code** |
| Ambient | cron + Automation Blueprints | full ignore→remember→monitor→act→ask→interrupt ladder into `govern_enqueue`, ≤4 interrupts/day — default-off, and its only wired event source is the camera feed | **Nerva** (transitively Frigate-gated) |
| Governance | always-on unbypassable blocklist + protected-path writes (no override, not even `--yolo`); gateway **default-deny** + DM pairing; smart approvals **auto-approve low risk**; container isolation **skips** command checks | risk-tier gate, taint→forced-ask, strict-local floor, secret broker, kernel (opt-in), `IntentLog` HMAC chain — but **channel pairing default-off**, Telegram approvals **unbound**, `AutonomyWorker.audit=None` in prod | **contested — see §4** |
| Proven on hardware | it is the product | **zero** — A1/A2/A7/A8 all ⬜ | **Hermes** |
| Head-to-head evidence | n/a | **none exists** | — |

---

## 2. What changed on both sides

**Hermes.** v0.17 (Reach): iMessage, background subagents, Automation Blueprints, WhatsApp Business
API, Skills Hub redesign *with security scanning*. v0.18 (Judgment): closed 949 issues including
its entire P0/P1 backlog (~692), Mixture-of-Agents first class, `/goal` completion contracts
verified against evidence, `/learn`, `/journey`, Vertex AI. v0.19 (Quicksilver, 07-20): ~3,300
issues closed, first-token latency −80%, **smart approvals as the default mode**, Bitwarden/1Password
secret sources, live subagent transcripts, a delivery-obligation ledger. Context for the velocity
figure: an open security-posture issue records **18,684 open issues** — "P0/P1 at zero" is a triage
statement against a very large backlog, not a claim of cleanliness.

**Nerva.** Since 2026-07-11 the repo shipped O29–O33 in code, the honesty layer (degradation stamps,
MOCK badges, capability-registry mirroring), a governance security audit, Mission Control, Projects,
desk presence. Real progress. But of the five pillar programs, **house and cameras have complete
in-repo paths** (only the external device is missing), while **media is driver-missing** and
**acquisition is caller-missing** — they terminate inside the repo, and no configuration reaches
them.

---

## 3. The four findings that change the story

### 3.1 The binding constraint is distribution, and we already have the data

The first draft called this repo "private, single-owner, 0 external users." **It is public** — 4
stars, 1 fork, 979 commits — and `docs/OWNER_TASKS.md:189` says so ("the repo was public
throughout"). Worse for the draft's ranking: `marketing/alpha-testing/2026-07-10-fb-response-triage.md`
records a recruiting campaign that ran 2026-07-08→10 and reached **39,642 impressions / 24,182
unique visitors / 165 interactions / 67 comments**, producing ~16 warm leads, 3 hardware-qualified
leads and 2 would-be *contributors*. Fifteen days later gate **A7 (recruit 1–3 design partners) is
still ⬜**.

Demand was tested and it exists. Conversion was zero. That makes time-to-first-value the **#1**
constraint, not the #3 the draft ranked it — and it means the next capability PR has a
demonstrated expected value of approximately nothing.

### 3.2 Our own defaults are worse than "off" — three of them are broken, not gated

The repo's standard frame is "correct but gated: flip the flag and it wakes." That is false in
three places, all in the **always-on** path or in the posture designed to switch things on:

- **Memory rehydration collides in the default install.** Session listing globs `*.json` in the
  memory root while the KG writes `entities.json` there; the moment a user mentions a proper noun,
  the newest `*.json` is not a session. A default user loses continuity across restarts. No flag
  causes this and no flag fixes it. `docs/COGNITION.md`'s troubleshooting table does not list the
  actual cause.
- **The learning loop is off even when you turn the intelligence layer on.** `product_posture.py`'s
  `WAVE1_FLAGS` (the "Companion Wave 1" / "Design Partner" presets — the deliberate owner-consent
  path) enable `cognition.enabled`, memory, learning, personality — and **omit
  `cognition.review_enabled`**. STATUS.md describes the loop as a merged "live wave." Nobody has
  ever run it. Fix: one line.
- **The action audit sink is `None` in production.** `AutonomyWorker` is constructed without
  `audit=`, so no approval, execution or failure is ever written to a chain. The `IntentLog` HMAC
  chain the kernel writes to is real and always-signed — but the kernel is default-off. So on a
  default install, "prove what it did" resolves to conversation logs, which is roughly what Hermes
  has too.

### 3.3 The governance moat is real but its headline claim was wrong

The draft's strongest sentence — "a machine-checked action-auth matrix that fails CI if a new action
kind escapes mediation" — is **refuted**. The test proves, for each of the **18 registered** kinds,
that the kernel is invoked with the flag on and not invoked with it off; it cannot see a kind that
was never registered. Two live counterexamples at HEAD with CI green: **`channel.reply`** and
**`skill.install`** both call `kernel.authorize` and are absent from `ACTION_REGISTRY` and the
snapshot. BACKLOG's "Gate-K COMPLETE — no bypass path exists" is doc-vs-code drift of exactly the
kind this document exists to catch.

Three more asterisks the draft missed, all pointed at the Hermes comparison:

- **The Telegram approval callback has no owner binding** in the production wiring (no
  `allowed_user_ids` passed; the callback discards `chat_id`/`user_id`; task ids are sequential).
  Telegram is our only live autonomy sink. Hermes documents a **default-deny** gateway ladder with
  DM pairing. On the single surface where both systems ask a human to approve something, **theirs is
  the locked one**.
- **Channel pairing is default-off**, and when disabled `is_allowed` returns True for everyone.
- **`JARVIS_ACTION_KERNEL` is not pure hardening.** Turning it on *removes* the wave-1 brokers'
  unconditional `autonomy_level="ask"` floor (a kernel GRANT sets `act`). And the O27–O30 facades
  need **two** flags (`JARVIS_UNIFIED_ACTION_API` *and* the kernel), so §6.4's "flip the kernel"
  would not light up house/media/desktop by itself.

Counterweight, and it is a real one: Hermes's approval story has holes we can name. `ha_call_service`
is **not** approval-gated ("HA events are always authorized"); container isolation **substitutes for**
command checks rather than stacking with them; "smart approvals" **auto-approve** low-risk commands;
memory writes default to no approval. And the single strongest fact in the whole comparison:
**Hermes issue #487, proposing a SHA-256 hash-chained action log, was closed as "not planned."**
They have decided not to build the thing our moat rests on. We have built it — and left it
disconnected in production.

### 3.4 The S1–S8 bars: better than the draft said, and still worthless for the purpose

The draft's "7 of 8 bars have no artifact" is **wrong**. Four bars have their NERVA_VISION-named
artifact green in CI today:

| Bar | Corrected status |
|---|---|
| S1 execution breadth | **artifact exists** — 7-case hermetic operator pack, runs in the default CI lane, drives the *real* drivers and *real* kernel against faked host edges. Not the required 20-task benchmark; `live_owner_validation: required`, `promotable: False` |
| S2 skill acquisition | **artifact exists and is stronger than the draft granted** — a dedicated mandatory `sandbox-isolation` CI job pulls `python:3.12-slim` and runs the real-Docker S2 probe on **every** PR and push, asserting reuse_rate and eleven governance invariants. Never promotes; no production path triggers acquisition |
| S3 multi-target | **artifact exists** (targets + audit-chain tamper tests) — but the module never executes and there is no SSH transport, so this is the *weakest* claim in the set, not the strongest |
| S4 context endurance | **no artifact and no subject** — the hot-path compressor is default-off; there is nothing to evaluate |
| S5 governance | **half green, half falsified by our own CI** — 18/18 zero-pending snapshot and `verify_chain` green, while `test_kernel_off_does_not_invoke_kernel` asserts that in the default configuration **zero** of the 18 kinds reach the kernel |
| S6 local-first | **structurally impossible today** — the egress monitor has one writer (plugin HTTP) while every LLM backend opens a raw client; a perfect `clean=True` would say nothing about model egress. In-memory, resets on restart |
| S7 personal-world | **unreachable by construction** — every P4–P6 reality pack is `promotable: False` and the harness is the only path to VERIFIED, so the registry can never mark these pillars verified no matter how green they run |
| S8 time-to-first-action | never measured |

The honest headline is not "7 of 8 have no artifact." It is: **4 of 8 have a CI-green artifact, 4
have none, and 8 of 8 have no artifact produced on real hardware or scored against Hermes** — which
is what the bars were written to measure. Nothing the harness produces is persisted anywhere: the
registry is in-process and resets on boot, and the reality workflow uploads no artifact.

---

## 4. Where Nerva genuinely leads

Stated at the strength the evidence actually supports:

1. **A tamper-evident action chain that Hermes has explicitly declined to build** (`IntentLog`,
   always HMAC-signed with an auto-provisioned out-of-tree key; issue #487 closed "not planned").
   Caveat that must travel with the claim: it only records what the kernel authorizes, and the
   kernel is opt-in.
2. **Taint → forced-ask**, genuinely not kernel-gated, applied on both intake paths. Nothing in
   Hermes's docs corresponds.
3. **A server-owned risk-tier floor** that fails closed to IRREVERSIBLE_OR_MONEY on unknown kinds.
4. **Strict-local agent classes** enforced above the router — a policy, not a config choice.
   (Hermes supports local inference first-class; its *default and recommended* posture is Portal +
   Tool Gateway, so search/media/cloud-browser egress is the happy path. That is a difference of
   enforcement, not of possibility — state it that way or it gets refuted in one link.)
5. **The physical-world program** — house graph + contracts + private store, camera privacy contract
   (consent leases, mandatory masks, TTL ceilings, no biometrics by construction), `present()`,
   ambient ladder with interrupt budgets. ~12k LOC in `house/`+`cameras/`+`ambient/`+`media_director.py`
   (~17.9k including `acquisition/`). Hermes has an `area` string filter and a per-family-member
   profile convention.
6. **The honesty machinery itself** — degradation stamps, MOCK badges, capability-registry state
   labels, and a culture of running adversarial audits on itself and publishing the losses. This
   document is the fourth such audit in eight days. It is a real asset; keep it.

---

## 5. Where the gap is widest, re-ranked

1. **Time-to-first-value** — empirically the binding constraint (§3.1). One `curl` line that
   provisions Python, Node, ripgrep and ffmpeg versus clone → `INSTALL.bat` → bring your own model →
   flip several undocumented env flags. The five webhook channels needing **no** extra dependency
   are the cheapest unshipped win in the repo.
2. **Actuation reality** — browser has no execution route; desktop has a complete chain blocked by
   an uninstalled package and an empty app allowlist. The honest contrast with Hermes is *"their
   opt-in is one documented command; ours is two undocumented flags plus a missing dependency"* —
   not "they act and we don't."
3. **The learning/memory experience** — theirs is on, visible (`/journey`), and writes freely; ours
   is ported, five-gated, invisible, and unreachable from the posture built to enable it.
4. **Voice** — a household member can talk to Hermes today (Discord VC, local Whisper, free Edge
   TTS) and cannot talk to Nerva at all, on any surface, in any shipped install.
5. **Velocity** — ~3,300 issues in one release versus one owner maintaining six pillars across seven
   ORIZONT programs, 404 routes, 5,406 tests, a HUD, a mobile app and WorldView. Breadth is the
   risk, not the asset.

---

## 6. What I'd actually do

1. **Close A8 and change nothing else until it lands.** Note what the pillar taxonomy means for that
   checklist: house and cameras are *configuration* work; `present()` on two non-chat surfaces
   requires **writing a MediaDriver from scratch** and an injection point that does not exist; the
   acquisition leg needs a contract factory and a trigger, not a caller.
2. **Ship the four one-line fixes before any of it** — they are hours, not sprints, and three of
   them are the difference between "gated" and "broken": (a) `cognition.review_enabled` into
   `WAVE1_FLAGS`; (b) session listing stops globbing `entities.json`; (c) pass `audit=` into
   `AutonomyWorker`; (d) bind the Telegram approval callback to the owner (SEC-B3) and default
   channel pairing on.
3. **Run the head-to-head once.** Install Hermes on the same box; 10 tasks across browser, desktop,
   house, and one skill acquisition; publish the table including the losses. Aim it at the tasks
   where Hermes documents *limits* — Windows admin-integrity windows (UIPI blocks them), Wayland
   without XWayland, password entry — because those are the ones a governed, host-native operator
   can win.
4. **Fix SEC-B1 with its preconditions stated** (cloud configured AND `cloud_fallback=always` or
   local down or prompt over the local window). Still Critical, still cheap; it is not a default
   leak, and overstating it is how a real finding gets dismissed.
5. **Restate the moat where it survives contact:** *"Hermes has HA as a tool; Nerva has a house
   model"* and *"Hermes decided not to build an action-level audit chain; we built one and have not
   turned it on."* Drop "Hermes can't touch a light" and drop "no household story" — both refute in
   one link.
6. **Re-baseline `NERVA_VISION.md`** §3's prose *and* §4's percentages (P1 ~35%, P4 ~20%, P5 ~15%;
   no pillar is stated as 0%), plus §98's stale "11 privileged action kinds" — the snapshot now
   covers 18. And register the four action kinds missing from `ACTION_REGISTRY`.
7. **Strategically: narrow what you turn *on*, not what you keep.** The ~12k LOC of physical-world
   code is the only thing Hermes has no answer to — deleting it deletes the reason to exist. But
   pick one vertical (governed household + strict-local family data), make it default-on, prove it
   on hardware, and stop hand-building the execution plane Hermes gives away under MIT.

---

## 7. The framing that survives audit

Hermes is a better *agent*. Nerva is trying to be a different *thing*, and the last three Hermes
releases (approvals, secret managers, evidence-checked goals, skill scanning) are evidence the
governance direction is right — they are bolting on individually what we built structurally, and
they have explicitly declined the hardest piece.

But architecture is not the axis this gets decided on. Hermes converts work into user-observable
capability every three weeks. We convert it into merged PRs — and we have already run the
experiment that proves this is the constraint: 24,000 people looked, 165 responded, nobody arrived.
The highest-leverage change available is not a feature and not a pillar. It is one vertical slice,
default-on, on real hardware, in the hands of somebody who is not the author.

---

## 8. Known limits of this analysis

- **Every Hermes fact is a vendor claim.** We read their docs and release notes; we did not install
  Hermes or audit its source. A 220k-star repo's docs can overstate too. The head-to-head in §6.3 is
  what converts this into evidence.
- **The completeness critic did not run** (session limit) — the 12th agent, which was to adjudicate
  contradictions between the eleven, failed. Where two agents disagreed I adjudicated by reading the
  source myself; anything I could not settle is marked in-line as unverified. One such item: the
  kernel's `authorize` does not strip a payload-supplied `risk_tier` despite a comment claiming it
  does — reachability from a caller-controlled payload is **unverified**, and settling it means
  auditing every `kernel(...)` call site (or simply popping the key).
- **No number here was measured on running hardware.** Everything is static analysis plus CI status.

## 9. Corrections to this document's own first draft

Kept deliberately, as the record of how the repo's story drifts when nobody checks it. The draft was
too generous to Nerva in six places and unfair to Hermes in five.

**Too generous to us:** "prod default is `NullBrowserDriver`" (there is no browser execution path at
all); "the action-auth matrix fails CI if a kind escapes" (it cannot discover new kinds; two escape
today); "S5 holds by construction" (CI pins the default to zero mediation); "presence" as a shipped
house capability (structurally always empty); "camera-event fusion into the same graph" (deliberately
isolated projection); "3 execution targets incl. ssh" (no SSH transport exists).

**Unfair to us:** 6 channels (there are 11); ~3 LIVE capabilities (4 — stock quotes landed);
`defusedxml` listed as missing (it ships); "7 of 8 bars have no artifact" (4 have CI-green ones);
"private repo" (public); desktop described as equivalent to browser (it is the one fully wired
chain).

**Unfair to Hermes:** "default-on browser toolset" (opt-in); desktop framed as turnkey (opt-in
install + OS grants); "~32k forks" (41.9k); "692 issues" as the velocity anchor (~3,300 in v0.19);
"no household story" (per-family-member profiles); "none documented" on rooms (an `area` filter
exists).

**Too generous to Hermes:** its HA tool calls are not approval-gated; container isolation replaces
rather than adds to command checks; "smart approvals" auto-approve low-risk commands; memory writes
need no approval by default; and it has explicitly declined to build a hash-chained action log.

**Sources — Hermes (fetched 2026-07-25):** `github.com/NousResearch/hermes-agent` · `/releases` ·
`/issues/487` · `/issues/40889` · `hermes-agent.nousresearch.com/docs/user-guide/features/{tools,browser,computer-use,memory,skills,voice-mode}` ·
`/docs/user-guide/{security,profiles,messaging,messaging/homeassistant}` · `/docs/integrations/providers` ·
`/docs/getting-started/installation` · `/docs/reference/toolsets-reference`.
**Sources — Nerva:** working tree `06cf011`; `project-status.json`; `BACKLOG.md`; `NERVA_VISION.md`;
`marketing/alpha-testing/2026-07-10-fb-response-triage.md`;
`docs/research/2026-07-18-live-vs-plumbing-capability-audit.md`;
`docs/research/2026-07-24-governance-rails-security-audit.md`; and direct file:line reads across
`agents/core/` (browser/desktop/kernel/house/cameras/ambient/acquisition/media/learning/memory/
channels/llm/environments/observability), `tests/`, `.github/workflows/`.
