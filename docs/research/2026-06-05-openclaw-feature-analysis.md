# OpenClaw — feature analysis: what to adopt, how to beat it

> Date 2026‑06‑05 · Goal: make Jarvis Hub **better than OpenClaw**. Grounded in the live repo
> (`github.com/openclaw/openclaw`, ~377k★) + our internal competitor research
> (`docs/research/2026-06-02-personal-ai-competitors.md`). A use‑case deep‑dive
> (`awesome-openclaw-usecases`) is a companion to this file.
>
> **Thesis (unchanged, now sharpened): "the governed OpenClaw."** OpenClaw proved the demand
> (always‑on personal AI on your own hardware) and the *liability* (ungoverned → first agent
> infostealer, Feb 2026). We win by matching its **reach/UX** while keeping — and **making visible** —
> our governance, memory, and observability.

## 1. What OpenClaw is (live repo)
Self‑hosted, always‑on, local‑capable. Features: **~23 messaging channels** (WhatsApp, Telegram, Slack,
Discord, Signal, iMessage, Matrix, Google Chat, Teams, LINE, WeChat, …); voice wake‑words + continuous voice;
a **"Live Canvas" (A2UI)** agent‑driven visual workspace; a **gateway** control plane; **per‑channel/account
agent isolation** with **Docker/SSH/OpenShell sandboxes**; **companion "nodes"** (Windows/macOS/iOS/Android as
remote execution nodes + menu‑bar/tray); cron + webhooks; **model failover + auth‑profile rotation**; **DM
pairing approval codes**; the **ClawHub** skills registry. `SOUL.md`/`MEMORY.md`/`*.json` memory + secrets are
**plaintext on disk**, the main session runs with **full host access**, the gateway is often **exposed** — the
exact infostealer vector.

## 2. Where Jarvis already wins (don't copy — this is the moat)
Reversible/irreversible **approval queue** · tamper‑evident **Merkle audit** · **capability tokens +
out‑of‑band kill‑switch** · **encrypted secret broker** (no plaintext) · **signed + moderated marketplace**
(anti‑ClawHub, H12.12) · **dual‑LLM quarantine + AgentDojo gate** (H17) · **bitemporal KG + nightly
consolidation + preference‑learning** (vs OpenClaw's vector blobs) · governed **payments** (H16.3) + **A2A**
with signed cards · **family‑local Frigga** · full **observability** (traces/eval/quality). On governance,
memory, and observability we are strictly ahead.

## 3. Adopt — *under governance* (close the reach/UX gap)
| Adopt | Governed Jarvis move | Backlog |
|---|---|---|
| **23‑channel breadth** (WhatsApp/Signal/iMessage/Matrix/Teams/Google Chat…) | More adapters on the existing gateway (rate‑limit + guardrails + allowlist apply); we have 6 today | **H12.16** |
| **"Nodes"** — phone/desktop as remote execution | A **governed node mesh**: nodes run only capability‑scoped, *approved* actions; home GPU stays the brain. Unifies Tauri (H11.1) + satellite‑split (H12.8) | **H12.17** |
| **Live Canvas / A2UI** — agent‑driven visual workspace | An **Agent Canvas** surface in the v2 HUD (the network brain is half‑way there), inspectable + governed | **H12.18** |
| **DM pairing approval codes** (unknown senders gated) | Inbound‑sender allowlist/approval on channels — mirrors the A2A allowlist | **H12.19** |
| **Auth‑profile rotation + model failover** | Rotate keys/accounts + failover in the hybrid router | **H12.20** |
| Per‑account agent isolation + sandbox backends | Already *more* governed via Data Spaces (H10.26) + LOCAL_ONLY + sandbox — extend per‑channel | (existing) |
| Continuous voice + native menu‑bar/tray | Tauri wrapper (H11.1) + continuous mode behind the mic‑mute indicator (H12.10) | (existing) |

## 4. How we end up *better* (not just at parity)
1. **Match the reach (§3) while keeping governance** — every new channel/node/action still flows through the
   approval queue + audit + guardrails. OpenClaw can't retrofit this without breaking its low‑friction model.
2. **Make governance visible** — the HUD v2 Trust Center (audit chain, kill‑switch, %‑local, capability grants),
   the signed marketplace badges, and the AgentDojo trust‑scorecard turn "we're governed" from a claim into a
   *shown, provable* property. OpenClaw has no observability surface at all.
3. **Better memory** — bitemporal KG + nightly consolidation + preference‑learning ("stops asking") is a real
   "knows‑you" engine vs OpenClaw's flat vector store.
4. **One‑line pitch:** *"Everything OpenClaw does — every channel, always‑on, acts on your machine — except
   every action is approved + audited, no secret is ever in plaintext, and there's no gateway to steal."*

## 5. Non‑negotiable guardrails (never copy)
OpenClaw‑style **ungoverned shell + plaintext secrets + exposed gateway + unmoderated marketplace** — the proven
failure mode. Counter‑position; never replicate. (Per `MOONSHOT.md` §5; ORIZONT 12 already encodes the governed
inverse.)

## Sources
- `github.com/openclaw/openclaw` (live, 2026‑06‑05) · `github.com/hesamsheikh/awesome-openclaw-usecases`
- `docs/research/2026-06-02-personal-ai-competitors.md` (internal) · `MOONSHOT.md` §5 · `BACKLOG.md` ORIZONT 12

## 6 · Use‑case deep‑dive — OpenClaw vs Jarvis (governed capability catalog)

A research pass over `awesome-openclaw-usecases` (42 documented use‑cases, 8 categories) + OpenClaw docs graded each against Jarvis (**have** / **partial** / **gap**).

**Coverage read:** Jarvis already **meets‑or‑beats** OpenClaw on **memory** (bitemporal KG + RRF fusion + nightly consolidation vs markdown files), **multi‑agent orchestration** (16 governed specialists vs ad‑hoc `sessions_spawn`), **security/governance** (approval queue, Merkle audit, secret broker, signed marketplace, per‑agent plugin gates, local‑only walls for family/health/finance), and **scheduling/autonomy** (heartbeat + reversible night‑shift). Most "partial" rows are *composable from parts we already ship*. OpenClaw's real lead is **actuation surface** + a thicker library of pre‑packaged "digest" skills.

**Per‑category gaps:** X/Twitter + social write‑actions (gap) · outbound voice / call‑back (partial→gap) · AI video editing + media‑gen (gap) · live generative‑UI canvas (partial) · photo‑OCR / screen understanding (needs VLM) · iMessage adapter (gap) · distributed nodes (gap, roadmapped).

### Top gaps to close to beat OpenClaw on use‑cases (prioritized)
1. **Governed browser / computer‑use (H15.1)** — *highest leverage.* Unblocks the largest cluster at once (overnight app builder, autonomous dev, local‑CRM scraping, market‑research→MVP, web check‑ins, video editing). Playwright/browser‑use behind the approval queue + sandbox + egress allowlist — every click gated + audited.
2. **Outbound voice / call‑back** (SuperCall‑style) — agent‑initiated calls on threshold + isolated voice persona; we have the voice pipeline + interrupt‑budget governance, need a Twilio/Telnyx outbound bridge. → **H12.22**
3. **Live generative‑UI canvas** — extend the workflow canvas to render agent‑produced HTML/dashboards (dynamic dashboards, second‑brain UI, LaTeX/PDF preview). → **H12.18**
4. **Local VLM / screen‑&‑document understanding (H13.1)** — Qwen3‑VL strict‑local; unblocks photo‑OCR + is the prerequisite for trustworthy screen‑grounded computer‑use.
5. **Governed node mesh (H12.17)** — phone/desktop as capability‑scoped execution surfaces; the brain stays on the home GPU.
6. **Packaged "digest" skills pack** — multi‑source news (weighted), earnings tracker, Reddit/YouTube/arXiv/HF digests, idea‑reality scorer — composable signed skills (low effort, high perceived breadth). → **H12.23**
7. **Governed social write‑actions** (X/Twitter post/reply/DM) — through the approval queue, OAuth/secret‑broker auth (not raw cookies). → **H12.21**
8. **Media generation** (images/thumbnails/video) for the content‑factory cluster. → **H12.24**
9. **Transcript‑watcher → tasks** (meeting notes → Notion/Todoist via approval queue) — building blocks exist, needs assembly. → **H12.25**
10. **iMessage / Instagram / Google‑Reviews channel adapters** (macOS iMessage is the notable one) — extends **H12.16**.

> The two biggest gaps (**H15 computer‑use**, **H12.17 node mesh**) are *already* the backlog's named OpenClaw comparators — the wedge holds: our lead is governed/local/audited **memory + orchestration + security**; OpenClaw's lead is raw **actuation**, which we close *under governance*.

**Sources:** `github.com/hesamsheikh/awesome-openclaw-usecases` (+ `usecases/*.md`) · OpenClaw docs (heartbeat / automation / tools / nodes / canvas) · Lenny's Newsletter, DigitalOcean, NVIDIA 2026 OpenClaw overviews.
