# Nerva (jarvis-hub) vs Hermes Agent — honest gap analysis (2026-07-25)

> **Immutable dated research doc** (per `docs/AI_CONTEXT.md`). Do not "fix" it later; write a new
> dated file when reality moves. Supersedes nothing — it *re-grounds*
> [`2026-06-07-hermes-agent.md`](2026-06-07-hermes-agent.md) (Hermes at v0.16.0, 185.7k★),
> [`2026-07-06-hermes-agent-migration-plan.md`](2026-07-06-hermes-agent-migration-plan.md) (the port plan)
> and the Hermes verdict in [`NERVA_VISION.md`](../../NERVA_VISION.md) §8, which is now **6 weeks stale
> on the Hermes side and 1 week stale on ours**.
>
> **Method.** Hermes side: live fetches of the GitHub repo page, the releases page, and the official
> docs (toolsets, computer-use, Home Assistant, installation) on 2026-07-25 — vendor claims, not
> code-audited by us. Nerva side: this working tree at `06cf011`, cross-read against the two audits
> the repo already did on itself (`2026-07-18-live-vs-plumbing-capability-audit.md`,
> `2026-07-24-governance-rails-security-audit.md`), `project-status.json`, and BACKLOG.
> Every "Hermes has X" below is *documented by Hermes*; every "Nerva has/hasn't Y" is traced to
> code or to our own audit.

---

## 0. The one-paragraph answer

Nerva is **architecturally ahead and operationally behind**, and the distance on the operational
axis is larger than any document in this repo currently admits. Hermes is a shipped product with
220k stars, a release every ~2–3 weeks, real browser and real desktop actuation on three OSes, 20+
messaging surfaces, 300+ models, and — as of the last two releases — *approval gating, secret-manager
integration and container isolation*, i.e. it is buying back some of the governance ground we
claimed as our moat. Nerva has a genuinely better *architecture* for the thing we say we want to
build (kernel-mediated action, hash-chained audit, taint, household privacy, bi-temporal memory, a
capability registry, a house/camera/media/ambient model Hermes does not attempt) and roughly
100k lines of backend plus 5,406 backend tests to back it — but in a bare install it does almost
nothing observable, the pillars are code-complete and **actuator-gated**, and the "superior to
Hermes" bar (S1–S8) has **never been measured against Hermes even once**. The honest summary:
*we are winning an argument no user has been able to check yet.*

---

## 1. Scoreboard

| Dimension | Hermes (2026-07-25) | Nerva (`06cf011`) | Who leads |
|---|---|---|---|
| Distribution / community | 220.1k★, ~32k forks, public product | private single-owner repo, 0 external users | **Hermes, by orders of magnitude** |
| Release cadence | v0.17 (06-19) → v0.18 (07-01) → v0.19 (07-20) | v0.11.0, tag 1.0 gated behind 9 open owner gates | **Hermes** |
| Real browser actuation | local Chromium/CDP + Browserbase + Browser Use, default-on toolset | `PlaywrightBrowserDriver` real but **default-off, not in `requirements.txt`**, prod default is `NullBrowserDriver` | **Hermes** |
| Real desktop actuation | `cua-driver` over MCP, macOS/Windows/Linux, background (no cursor steal), a11y + screenshots, per-action approval | `GovernedDesktop` + Windows/pywinauto seam, **two flags off by default, pywinauto not installed**, `NullDesktopDriver` | **Hermes** |
| Terminal/exec targets | 6 backends (local, Docker, SSH, Singularity, Modal, Daytona) | 3 (local, docker, ssh) **+ per-target policy and audit chain Hermes has no analogue of** | Hermes on breadth, **Nerva on governance** |
| Model providers | 300+ models via Portal/OpenRouter + Vertex, Fireworks, DeepInfra, custom | 6 `ProviderProfile`s + hybrid router + LM Studio control + local-residency detection | **Hermes on breadth**, Nerva on local-first |
| Channels | Telegram, Discord (+VC voice), Slack, WhatsApp (Business Cloud), Signal, iMessage, email, CLI, HA, Raft, desktop app | web SSE, Telegram, Discord, Slack, email, voice — **Discord/Slack SDKs not in base requirements**; Telegram is the only real autonomy sink | **Hermes** |
| Skill/learning loop | `/learn`, `/journey`, curator with cost-optimised idle sweeps, Honcho user modelling, memory batching — **on by default** | ported loop (`learning/background_review.py`, CoreMemory, curator, usage/provenance) — **behind the cognition master switch, default-off, needs a local LLM** | **Hermes in practice** |
| Home Assistant | `ha_list_entities` / `ha_get_state` / `ha_list_services` / `ha_call_service` + HA as a conversation-agent channel, **on when `HASS_TOKEN` is set** | real REST+WS adapter (`house/home_assistant.py`, 610 LOC) — returns `disabled` unless two env flags **and** a LAN HA | **Hermes today**; Nerva on the model (see §3.2) |
| Room/occupant/presence model, household policy | none documented | `house/graph.py`, `presence.py`, `private_store.py`, `confirmation.py`, per-person authority | **Nerva** (unproven) |
| Cameras / surveillance | none documented | 4.5k LOC: privacy contract, Frigate read-only, ONVIF discovery, event vault, NL retrieval | **Nerva** (needs a LAN Frigate + consent) |
| Media / presentation fabric | image gen, TTS, vision | `media_director.py` `present()` (878 LOC) + Spotify — `NullMediaDriver` by default | **Nerva** (unproven), Hermes n/a |
| Ambient / decision ladder | cron + automation blueprints | `ambient/` (3.8k LOC) ignore→remember→monitor→act→ask→interrupt + interrupt budgets (≤4/day) | **Nerva** (default-off) |
| Governance | smart approvals (LLM-assessed), hard-blocked patterns, DM pairing, container isolation, blocked HA service domains, Bitwarden/1Password secret sources | Action Kernel + contracts + risk tiers + taint + hash-chained audit + budgets + kill-switch + signed skills + quarantine + strict-local agents | **Nerva** — but narrower than the docs claim (§3.1) |
| Proven on real hardware | it is the product; people run it | **zero** — A1 ⭐B0, A2 72h soak, A7 design partners, A8 AI-OS owner-host proof all ⬜ | **Hermes** |
| Head-to-head evidence | n/a | **none exists** | — |

---

## 2. What changed since our last look (both sides)

**Hermes moved fast, and toward us.** v0.17 (Reach) added iMessage, background subagents, image
editing, Automation Blueprints, WhatsApp Business API, a Skills-Hub redesign *with security
scanning*, and curator cost optimisation. v0.18 (Judgment) closed ~692 P0/P1 issues in one cycle,
made Mixture-of-Agents first-class, added `/goal` **completion contracts where the agent verifies
work against evidence** (that is our Verification Fabric's pitch), `/learn`, `/journey`, and Vertex
AI. v0.19 (Quicksilver, 2026-07-20) cut first-token latency ~80%, made **smart approvals the
default**, added **Bitwarden/1Password secret sources**, live subagent transcripts, a
**delivery-obligation ledger** (no silently lost responses), and profile-based routing.

Read that list against our differentiators: approvals, secret handling, evidence-checked task
completion, and skill-supply-chain scanning were all things we listed as "where jarvis leads" in
June. They are no longer empty on Hermes's side. What Hermes still has *no* answer for is the
tamper-evident audit chain, taint/dataflow labelling, risk-tiered kernel mediation, strict-local
family data, and the entire physical-world layer.

**We moved too, and mostly in code, not in proof.** Since 2026-07-11 the repo shipped O29–O33
end-to-end (media director, house brain, cameras, acquisition, ambient — all ✅ in BACKLOG), the
live-vs-plumbing honesty layer, a governance security audit, Mission Control, Projects, and desk
presence. `NERVA_VISION.md` §3's "honest baseline" (cameras: nothing exists; no HA integration; no
media abstraction) is **stale in our favour** — that code now exists. But §8's Hermes verdict is
stale *against* us: it says Hermes lacks the house, and Hermes now ships HA device control.

---

## 3. The three uncomfortable findings

### 3.1 Our moat is real but has holes we found ourselves and haven't closed

The governance stack is the single strongest thing in this repo and nothing in Hermes compares to
it. But per our own 2026-07-24 adversarial audit:

- `JARVIS_ACTION_KERNEL` is **opt-in** — the README was corrected on 2026-07-24 from "every
  autonomous action crosses one Action Kernel" to "converging on one Action Kernel mediation point
  (opt-in while it hardens)". The always-on rail is the risk-tier gate, not the kernel. The
  flip-on criteria are still an open owner decision.
- **SEC-B1 (Critical, open):** `Agent.synthesize` can carry a strict-local agent's raw output
  (Frigga = family data) into a cloud-eligible synthesis call. That breaks the hardest promise we
  make, and it is the promise the whole local-first wedge rests on.
- **SEC-B2 (open):** "tamper-evident audit" and `REQUIRE_SIGNED_SKILLS` only hold when an optional
  key env var is set; unkeyed digests are integrity-only. The label over-promises.
- The audit's headline is still good news — the core "can't act ungoverned by default" invariant
  **holds** across all six action families, kernel-off path included, and the classifier fails
  closed. But "our governance beats Hermes's approvals" is a claim with three asterisks on it right
  now, and one of them is Critical.

### 3.2 The house-brain moat is narrower than `NERVA_VISION.md` §8 says

The vision doc asserts Hermes "would still lack unified physical-world state, household identity/
permissions, continuous perception, event correlation, room-aware output, graded physical
authority, local video processing, and low-noise ambient autonomy." Most of that list is still
true. But the *entry point* is no longer ours alone: Hermes ships four `ha_*` tools, enabled by a
single `HASS_TOKEN`, with dangerous service domains blocked, plus Home Assistant as a conversation
channel — so a Hermes user can today say "turn off the hallway light" and have it happen, while a
Nerva user gets `{"status": "disabled"}` until they flip `JARVIS_HOUSE_BRAIN` + `JARVIS_HOME_ASSISTANT`
and point it at a LAN HA.

The defensible framing is narrower and still correct: **Hermes has HA as a tool; Nerva has a house
model.** Rooms, occupants, presence, per-person authority, privacy zones, camera-event fusion into
the same graph, interrupt budgets — none of that exists in Hermes. But we should stop saying
"Hermes has no house" and start saying "Hermes can toggle a light; Nerva is trying to understand
the household" — and then *prove the second half*, because right now both claims read identically
to a user: nothing happens.

### 3.3 "Superior to Hermes" is currently unfalsifiable

`NERVA_VISION.md` §8 defines S1–S8 with the right instinct ("measured, never asserted"). Current
evidence status:

| Bar | Required evidence | Actual state |
|---|---|---|
| S1 execution breadth | 20-task browser/computer benchmark, kernel ON | **no benchmark exists**; H28.5 is 7 hermetic contracts against fake drivers, `promotable:False`, `live_owner_validation:required` |
| S2 skill acquisition | end-to-end acquire→verify→approve→register + reuse rate | H32.7 exists but is a **non-promoting** monkeypatched Docker contract; the real-Docker lane is behind `RUN_SANDBOX_ISOLATION=1`; no prod path auto-triggers acquisition |
| S3 multi-target execution | local/docker/ssh + per-target policy + audit | closest to real — `environments/targets.py` is genuinely the thing Hermes lacks |
| S4 context endurance | ≥95% eval success compressed vs uncompressed | compressor merged (#634); no published eval number found |
| S5 governance | kernel-mediated 100%, taint live, `verify_chain` green | holds by construction with the caveats in §3.1 |
| S6 local-first | full loop, zero external calls, LOCAL_ONLY | monitor exists (H23.16); no recorded clean run of the *full* loop |
| S7 personal-world moat | VERIFIED capabilities on P4–P6 | registry states exist; **A8 (owner-host proof) is ⬜ blocking** |
| S8 time-to-first-governed-action | <30 min fresh install | never measured |

Seven of eight bars have no artifact. Meanwhile Hermes's equivalent claim ("it works") is
continuously validated by 220k stars' worth of users. **A bar nobody has stood on is not a bar.**

---

## 4. Where Nerva genuinely, durably leads

Not hedged — these are real and Hermes has no equivalent:

1. **Kernel-mediated action with contracts, risk tiers, budgets and a kill-switch.** Hermes's
   smart approvals are a per-command prompt; ours is an authorization layer with a machine-checked
   action-auth matrix snapshot (`tests/test_action_auth_matrix.py`) that fails CI if a new action
   kind escapes mediation. That is a categorically different guarantee.
2. **Hash-chained audit + taint labelling.** Nothing in Hermes's docs answers "prove what it did
   and where that data came from."
3. **Strict-local agent classes** (Frigga family memory) and LOCAL_ONLY posture as a *policy*, not
   a deployment choice — Hermes's local story is "point it at your endpoint"; its default
   tool-gateway path routes search/media through Nous-hosted services.
4. **The physical-world program**: house graph + presence + camera privacy contract (consent
   leases, mandatory masks, TTL ceilings, no biometrics by construction) + `present()` fabric +
   ambient decision ladder with interrupt budgets. ~12k LOC across `house/`, `cameras/`,
   `ambient/`, `media_director.py` with no counterpart in Hermes.
5. **Bi-temporal KG + RRF fusion memory** vs Hermes's flatter procedural memory + FTS5 session
   search.
6. **Institutional honesty machinery** — `plugins/degradation.py`, MOCK badges, the capability
   registry `state` labels, and the fact that this repo runs adversarial audits *on itself* and
   writes down that only ~3 user-facing capabilities are LIVE. Most projects at this stage lie to
   themselves; this one doesn't. That is a real asset and it should not be traded away.

---

## 5. Where the gap is widest, ranked by how much it costs us

1. **Actuation reality (P3).** Every action surface degrades to a `Null*Client` / `deferred` /
   `disabled` in the default config. Hermes clicks buttons on three OSes today. This is the gap.
2. **Velocity asymmetry.** One release of Hermes closed ~692 P0/P1 items. We are one owner plus
   agents, currently maintaining **seven** capability pillars, 404 routes, 5,406 backend tests,
   ~100k backend LOC, a HUD, a mobile app, and WorldView. Breadth is our biggest strategic risk,
   not our biggest asset.
3. **Time-to-first-value.** `curl | bash` and Hermes provisions Python, Node, ripgrep, ffmpeg and
   asks you to pick a model. We need LM Studio or keys, optional engines (`playwright`,
   `faster-whisper`, `edge-tts`, `pywinauto`, `bs4`, `defusedxml`, `discord.py`, `slack_sdk`) that
   are deliberately not in base requirements, plus flags. S8 (<30 min) is plausible only for the
   author.
4. **The learning loop is off.** We ported Hermes's identity feature and then gated it behind the
   cognition master switch + a local LLM. Hermes's runs by default and now has `/journey` to make
   it *visible* — which is why users believe it learns and nobody can tell whether ours does.
5. **Ecosystem.** Skills Hub with security scanning, MCP, 20+ platforms, a themed desktop app,
   subscription billing. We have a signed marketplace with, effectively, one publisher.

---

## 6. What I'd actually do (ranked, opinionated)

1. **Stop opening pillars. Close A8.** The AI-OS owner-host proof is already written and already
   the blocking gate: Playwright + Windows UIA actuation, real HA state + graph + governed device
   action, one consented Frigate event through house→memory→ambient, presence-aware `present()` on
   two non-chat surfaces, one approved acquisition→reuse. Nothing else in this document matters
   until that runs once on the RTX box with evidence recorded. Every ✅ in O27–O33 is currently a
   promise.
2. **Run the head-to-head, once, honestly.** Install Hermes on the same hardware. Define 10 tasks
   (not 20 — 20 will never happen) spanning browser, desktop, house, and a skill acquisition. Score
   both. Publish the table including the losses. That single artifact is worth more than the S1–S8
   framework, and it converts "superior to Hermes" from a slogan into a number. Budget: a day.
3. **Fix SEC-B1 before anything else in the security lane.** A strict-local leak in synthesis
   invalidates the one promise that Hermes structurally cannot make. It is also cheap: pin
   synthesis to the strictest contributor policy + a regression test.
4. **Pick the three flags that go on by default and defend them.** Candidates in order:
   the learning loop (with a local model), `JARVIS_ACTION_KERNEL` (the flip-on criteria are already
   an open owner decision), and the Playwright driver with `playwright` moved into
   `requirements.txt` as an extra. Default-off everything is why the product "does less than the
   PRs imply."
5. **Rewrite `NERVA_VISION.md` §8's verdict** — Hermes now has HA device control, approval gating,
   secret managers, evidence-checked goals, and skill-hub scanning. Keep the strategy (adopt, don't
   rebuild; spend our engineering on kernel + house + cameras + media + ambient) but restate the
   moat as **"Hermes acts; Nerva can prove what it did and models the household it acts in"** —
   and drop any claim that implies Hermes can't touch a light.
6. **Re-baseline `NERVA_VISION.md` §3** — the pillar percentages (cameras 0%, no HA, no media) are
   two weeks out of date on the code axis. Replace percentages with the LIVE/PLUMBING/STUB rubric,
   which is the honest unit and one we already own.

---

## 7. The framing I'd keep

Hermes is a *better agent*. Nerva is trying to be a *different thing* — a household operating
system with a legal-grade record of its own behaviour. That bet is still good, and the last six
weeks of Hermes releases (approvals, secret managers, evidence contracts) are evidence that the
governance direction is right, not that it is crowded: they are bolting on individually what we
built structurally.

But the bet is only good if it ships. The asymmetry that decides this is not architecture — we win
that — it is that Hermes converts work into *user-observable capability* every three weeks and we
convert it into merged PRs. The single highest-leverage change available is not a feature: it is
turning one vertical slice all the way on, on real hardware, and letting somebody who isn't the
author use it.

**Sources (Hermes side, fetched 2026-07-25):** `github.com/NousResearch/hermes-agent` ·
`/releases` (v0.17.0 · v0.18.0 · v0.19.0) · `hermes-agent.nousresearch.com/docs` ·
`/docs/user-guide/features/tools` · `/docs/user-guide/features/computer-use` ·
`/docs/user-guide/messaging/homeassistant` · `/docs/getting-started/installation`.
**Sources (Nerva side):** working tree at `06cf011` — `project-status.json`, `BACKLOG.md`
(ORIZONT 27–33, live-vs-plumbing epic, release gates A1–A9), `NERVA_VISION.md` §3/§8,
`docs/research/2026-07-18-live-vs-plumbing-capability-audit.md`,
`docs/research/2026-07-24-governance-rails-security-audit.md`, and direct reads of
`agents/core/{browser_playwright,browser_agent,desktop_operator,media_director}.py`,
`agents/core/{house,cameras,ambient,acquisition,kernel,environments,llm/providers,channels}/`.
