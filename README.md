# Nerva — your AI cabinet

**Current sprint → [Hermes equivalence: status of all 697 capabilities](HERMES_STATUS.md)**

![Python 3.12](https://img.shields.io/badge/python-3.12-blue?logo=python&logoColor=white)
![License: Apache 2.0](https://img.shields.io/badge/license-Apache--2.0-blue)
<!-- project-status:badges:start -->
![Backend tests](https://img.shields.io/badge/backend_tests-37908-brightgreen?logo=pytest)
![Version](https://img.shields.io/badge/version-1.0.0-orange)
<!-- project-status:badges:end -->

> 17 specialized AI agents orchestrated through Jarvis, running on **your own hardware**, controlled by voice and web.

**A private AI OS that cannot silently act beyond the authority you grant it.** Local-first and governed: every autonomous action is risk-gated — a reversible/irreversible **approval queue** for anything consequential, a tamper-evident **audit log**, budgets and a kill-switch, converging on one **Action Kernel** mediation point (opt-in via `JARVIS_ACTION_KERNEL` while it hardens) — and it runs entirely on your own hardware (LM Studio / Ollama on your GPU), **$0/month, no cloud by default**, with a **family agent that never touches the internet**. Where other local agent systems prioritize extensibility and raw autonomy, this system prioritizes governed execution, local ownership, and inspectability. The product it is becoming is **Nerva** (published by Digitaholic; `jarvis-hub` remains the repo codename until the deliberate rename) — the long-term product & capability vision (house brain, media director, cameras, computer operator, self-extension) is in [`NERVA_VISION.md`](NERVA_VISION.md).

**Get running in minutes →** [Quickstart](#run) · one-click `INSTALL.bat` on Windows.

<!-- TODO(launch): demo GIF above the fold — 30–60s of a real task incl. one approved irreversible step -->

---

## What this is

A personal AI mesh that handles the cross-section of *your* life: the day job and the side business, the family, the car and the house projects, fitness, finance, content. Each domain has a dedicated agent. They talk to each other through Jarvis. They learn from interactions.

**The agents ship as templates and personalize themselves in your first session:** guided onboarding (drop-folder import + profile memory) teaches Jarvis your people, projects, and preferences, every learned fact is inspectable and deletable, and each agent's personality is editable. Your personalized souls live in gitignored `agents/<id>/SOUL.local.md` overlays — the public repo stays generic, your instance stays yours. The roster below shows each agent's *role*; the specifics become yours.

## Architecture

**Pure local Python + opt-in plugin layer.** *Not* OpenClaw — deliberately: where the viral 2026 rival stores secrets in plaintext and runs ungoverned community skills (widely reported in 2026 as a major infostealer target — analysis: [`docs/research/2026-06-02-personal-ai-competitors.md`](docs/research/2026-06-02-personal-ai-competitors.md)), here every action is gated by a reversible/irreversible approval queue, guardrails, and an audit log. No cloud dependency by default. Every third-party service is an explicit, scope-limited, audit-able, disable-able plugin.

## The cabinet

**CNS (Command tier)** — 4 agents:
- **Jarvis** — Prime Orchestrator. The voice you wake.
- **Friday** — Daily Intel. Weather + news + market signal.
- **Pepper** — Chief of Staff. Calendar + meetings + reflection.
- **Jerome** — Leisure & Soundtrack. Music, retro tech, decompression.

**Business tier** — 5 agents:
- **Athena** — External Strategist. Your side business, personal brand, career trajectory.
- **Stark** — Internal Corporate Intel. Day-job KPIs, board prep, channels.
- **Veronica** — The Voice. Drafts emails, posts, captions in 5 voice profiles.
- **Vision** — Deep Researcher + OSINT. Cited synthesis, regulatory watch.
- **Argus** — Geoint Sentinel. Read-only, governed bridge to the Signal Layer.

**Tech tier** — 3 agents:
- **Steve** — CTO + Infrastructure. Bonobo + Pi + models + backups.
- **Oracle** — Pipeline Weaver. n8n workflows, silent when working.
- **Ultron** — The Shield. Firewall, GDPR/ATT, smart home VLAN.

**Foundation tier** — 5 agents:
- **Gecko** — Capital Allocator. Numbers cold; no advice.
- **Hercules** — Physical Engine. Sleep, recovery, training prep.
- **Hephaestus** — Builder & Mechanic. Your project car and house build.
- **Frigga** — The Matriarch. Family memory and care — names, dates, routines. Strictly local-only.
- **Howard** — Digital Twin (emerging). Voice clone, personal RAG, fine-tune candidate. Local-only.

## Hardware

**What model should I run?** Jarvis works with any LM Studio / Ollama model — pick by VRAM:

| Your GPU | Recommended local model | Expectation |
|----------|------------------------|-------------|
| 8–12 GB (3060/3080) | `qwen2.5:7b` / `llama3.1:8b` (Q4) | solid daily chat; deep-think slot off |
| 16 GB (4080/4070Ti S) | `qwen2.5:14b` / `gemma2:27b` (Q4) | good quality, one model slot |
| 24 GB+ (3090/4090/5090) | `gemma-4-31b-a4b` (MoE) + a deep slot | the full reference experience |
| CPU-only | `qwen2.5:3b` | it works; expect slow replies |

No GPU rule is enforced — the model picker (`/api/onboarding/command-center`, HUD → Start) tells you honestly whether a model is reachable. The measurement protocol and the per-tier table live in [`docs/HARDWARE_BENCHMARKS.md`](docs/HARDWARE_BENCHMARKS.md) — the numbers themselves are not measured yet (owner hardware), and that page stays blank rather than guessing. The reference rig below is what the project is developed on, **not a requirement**:

- **Bonobo WS** (Pop!_OS) — Intel Core Ultra 9, 192GB DDR5, RTX 5090 24GB, 4× NVMe + 18TB HDD
- **Pi 5** — always-on services (Qdrant, Neo4j, n8n, Homebridge)

**Providers & platforms.** Any OpenAI-compatible endpoint works, not just LM Studio/Ollama:
**OpenRouter** and other OpenAI-compatible backends ship today (`agents/core/llm/openrouter.py`,
switch with `/model`). **Apple Silicon (M1–M4)** is covered — `install.sh` handles macOS; run
local models via LM Studio/Ollama on unified memory (owner smoke-tests tracked as FB1). Running
on a lean box or a server/TUI? Use the **`headless`** usage profile (`JARVIS_SYSTEM_PROFILE=headless`)
— heavy media features off, background autonomy on, local-light models. Full platform/provider
support: [`docs/COMPATIBILITY.md`](docs/COMPATIBILITY.md); tester-level answers: [alpha FAQ](marketing/alpha-testing/FAQ.md).

## Stack

- **Orchestration:** Python 3.12 + asyncio + FastAPI
- **LLM inference:** LM Studio (OpenAI-compatible, primary) → Ollama (fallback) → optional cloud (Anthropic/OpenAI) for approved agents
- **Model:** `google/gemma-4-31b-a4b` (MoE, ~4B active params) on RTX 5090
- **Voice:** browser-mic HUD loop ships; server engines are optional manual installs (openWakeWord wake word, faster-whisper STT, edge-tts / Kokoro TTS) — no install path ships them ([`docs/VOICE.md`](docs/VOICE.md))
- **Memory:** conversation history (JSONL) + vector store (real embeddings via LM Studio/Ollama, hash fallback) + knowledge graph + fused recall (RRF, vector ⊕ graph) + SQLite checkpoints (WAL)
- **Channels:** web (SSE), voice, telegram, discord, email, slack
- **Security:** PII/secret scanner, SSRF protection, audit log (Merkle chain), guardrails (WARN/REDACT/BLOCK)

### Signal Layer


The **Jarvis Signal Layer** is the provider-neutral situational-awareness API at `:8787`. It turns provider data into evidence, signals, relevance, assessments, briefs, and approval-gated recommendations. It starts in deterministic replay mode by default and can later use a WorldMonitor sidecar as provider #1. The WorldMonitor sidecar convention is `:3100`. See [`services/signal-layer/README.md`](services/signal-layer/README.md).

## Run

<!-- project-status:run:start -->
Generated test matrix: backend **37,908** · frontend **5,011** · mobile **522**. Route surface: **940**.
<!-- project-status:run:end -->

**One step per OS.** Every path ends the same way: a `.venv` with the **hash-pinned**
dependency set, a passed **install smoke** (real boot + `/readyz` + one deterministic chat turn),
and the Command Center open at `http://127.0.0.1:8080/v2` — bound to **loopback only**. No cloud
key is asked for at any point. Requires **Python 3.12+**; a local model runtime (Ollama / LM Studio)
is detected, never installed.

```bash
# Linux / macOS — hosted one-liner (clones into ~/nerva, or $NERVA_DIR)
curl -fsSL https://raw.githubusercontent.com/andrei649/jarvis-hub/main/install.sh | bash

# …or, from a checkout
./install.sh                 # venv + locked deps + smoke, then starts Nerva and opens /v2
```

**Windows 11:** double-click **`INSTALL.bat`** — it checks for Python 3.12 (offers `winget` when
missing), builds the environment from the lock, and then offers to start Nerva; **`START.bat`**
launches it later. *(PowerShell / packaged executable: `packaging\windows\install.ps1 -Launch`.)*

```bash
# Docker, if you would rather not touch the host at all (loopback posture, same as native)
docker compose -f docker-compose.quickstart.yml up --build

# Something not working? One command, named reasons, exit 0/1
python scripts/doctor.py
```

Full per-OS detail: **[`docs/INSTALL.md`](docs/INSTALL.md)**. Reaching the HUD from your phone or a
second device on the LAN — what the boot guards refuse and the one supported way through:
**[`docs/PHONE_ACCESS.md`](docs/PHONE_ACCESS.md)**.

_Manual, if you prefer to drive it yourself:_

```bash
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements-beta.txt                 # one install — full feature set
python serve.py              # → http://127.0.0.1:8080
python -m pytest             # full offline suite — current count auto-synced in STATUS.md
```

_Also on Windows:_ **`UPDATE.bat`** pulls the latest and reinstalls. The optional Signal Layer
is **opt-in** on every platform: `JARVIS_SIGNAL_LAYER=1` starts it at `:8787`. If something you added breaks the hub (a persona
overlay, a skill, a scheduled job, an MCP server), **`python serve.py --safe-mode`** starts it with
only what ships: nothing of yours is deleted, the HUD says SAFE MODE, and a normal restart brings it all back.

_Changed your mind?_ `./uninstall.sh --confirm` (`UNINSTALL.bat` on Windows) removes the
installer-created Python environment (`.venv/`). Files outside the current installer footprint are preserved.
Your data is never touched unless you also pass `--purge-data`.

- **HUD:** http://127.0.0.1:8080/ — the **V2 cockpit** (primary HUD; legacy HUD at `/v1`, override with `JARVIS_HUD=v1`)
- **Signal Layer:** http://127.0.0.1:8787/healthz (replay mode by default; opt out with `JARVIS_SIGNAL_LAYER=0`)
- **Admin panel:** http://127.0.0.1:8080/admin
- **CLI REPL:** `python agents/run.py`
- **Scripted chat:** [CLI receipts and session attribution](docs/cli-chat-receipts.md).

### Open an existing profile from this checkout

Point the launcher at the named profile directory that already holds your settings,
tasks and memory. For example, on Windows:

```powershell
.\.venv\Scripts\python.exe -I scripts/start_profile.py "C:\Nerva\data-profiles\studio"
```

On Linux or macOS, use `.venv/bin/python` and the absolute path to your profile.
Add `--check` to see the selected checkout and profile before starting. The
launcher binds the hub to loopback and uses the port and vault in the profile's
own `.env`. Open the local URL printed at startup. Stop the running hub with
Ctrl+C before using the same profile from another checkout.

Under a chat reply, **Agent tool calls recorded** shows how many tool executions
the hub observed for that turn. A draft can show zero. For a message you asked
the agent to send, check the messaging service's confirmation for delivery.

When you pick an agent in Chat or Cockpit, refreshing the same tab restores
the recipient for that conversation. If the selected agent becomes unavailable,
choose another before sending. A fresh tab starts with Jarvis.

To find an earlier message, open **Search chat history** in Chat or Cockpit
with owner access. Enter words from the message and choose **Review source**
to see the saved turn. **Continue this conversation** reopens its conversation
and keeps the text in your composer. Search returns up to 20 matches.
On iOS and Android, open **Chat → History → Search messages** to find and reopen a conversation.

To quote an earlier message in your current web chat, select a passage in the
review and choose **Use in this chat**. Your draft and selected agent stay in place.
You can remove the passage before sending. If the agent can use a cloud model,
confirm that it may receive the passage. When you send, the hub checks the saved
message again. The question in your history keeps a citation to the source.
On iOS and Android, choose **Use passage in next message** in the source review
to attach the passage to your current draft.

### Saved facts in chat

In the HUD, open **Memory → Saved facts**. Choose **Agent notes** for a project
fact or **User profile** for a preference, then save it. Use **Correct fact**
when the information changes. New owner chats can include these facts in the
selected model's prompt. Each fact also has **Forget fact**, with an undo
option after removal. Curated facts are stored in the hub profile. The Obsidian
picker reads the notes you choose for a particular message. To find a source
again later, select its excerpt and include its relative path in your message.
The model sees the path, and you can copy it from chat history.

In Chat, Cockpit or the mobile app, choose **Remember message** under your own
message. Edit the text and choose **Agent notes** or **User profile**. To update
an earlier preference, choose **Replace a saved fact**, select the old wording,
then confirm the correction. For a new fact, choose **Save fact**. New owner
conversations can use the correction when automatic memory is on. The original
message stays in chat history. To remove a shared preference, choose **Forget a
saved fact**, select its store and wording, and confirm. **Undo forget** can
restore it while the saved facts still match the state after removal. Chat
transcripts and Obsidian notes have their own copies.
To ask about an existing note, type a question and tap **Obsidian notes**. Review
the matching passages from your connected hub and choose **Send with notes**.
The search can find a lesson near the end of a long note even when the title
contains none of your search words. In web Chat and Cockpit, **Choose passage**
opens the matching part of the note so you can highlight the exact text to share.
If the selected passage changes before you send it, Chat asks you to review it again.

To keep a completed reply in your vault, choose **Save to Obsidian** under the
reply in mobile Chat, web Chat or Cockpit. Review the destination vault and inbox, edit the
title and note, then choose **Save note**. The confirmation shows the saved
Markdown path. **Open in Obsidian** opens the note when a native link is available.
If another note already uses your title for different text, choose a new title.
If the connection drops during the save, **Retry save** checks the same request.
On mobile, tap **Open saved note** to read the current version from the hub.
The link is retained with the conversation cached on that phone.

### Ask about a Word document or Excel workbook

In web Chat or Cockpit, choose **Files** and open a `.docx` or
`.xlsx` file. Select a passage or worksheet rows and attach them. Choose
**Add another document** to compare up to eight passages in one question.
For example, attach the agreed dispatch date from a Word contract and the
booking date from an Excel sheet, then ask how many days apart they are.
Each passage is labeled with its filename and, for Excel, its sheet. Use
**Review attached passage** to change a selection from the same source. The hub opens each
file for preview. The selected agent receives the labeled passages.
In a long Word document, choose **Next page** or **Previous page** to review
12,000 characters at a time. Excel previews show up to 32 nonempty worksheets
and the first 12,000 characters of each. Choose **Download Word** below
the completed reply to save the comparison as an editable document.

### Edit an agent reply in Photoshop

In web Chat or Cockpit, choose **Photoshop** below a completed reply. Edit the
title and body, optionally choose a local PNG or JPEG, and check the preview.
Choose **Download PSD** to save a 1200 × 800 document. In Photoshop you can edit
the text layers or move the image independently. Photoshop may ask to update a
text layer on its first edit. Check the line breaks afterward. The browser
builds the PSD locally.

### Ask for a reply in another language

Write the language into the current message, for example **Răspunde în engleză**
or **Reply in Romanian**. The choice applies to that reply, including a draft
you ask an agent to write. You can keep the interface and your source notes in
their usual languages.

### Ask about a Blender project

In **Artifacts**, choose **Inspect Blender file** and select a `.blend` file
up to 64 MiB. In Chat, click **Inspect with Blender** to upload it to your hub.
The hub needs an installed copy of Blender. Choose a section such as **Objects**,
select the names you want to share, and send your question. The agent receives
the selected text. A saved thumbnail, when available, appears in your preview.

### Create an editable Blender model

In web Chat or Cockpit, describe the shape and dimensions, then choose
**Make editable Blender model**. You can review the request before sending it
to the selected agent. For example, ask for a square pyramid named Beacon
with a four-unit base and a tip three units above its center.

When the agent returns a supported Wavefront OBJ block, choose **Review Blender model**
to see the shape, object counts and any warning about inconsistent face orientation
or a closed shell that appears to face inward.
Choose **Download Blender project** to have the connected
hub build a native `.blend` file. Open it in Blender and switch to Edit Mode to
work on the vertices and faces. This export supports named polygon meshes in
Blender XYZ coordinates. It requires owner access and Blender installed on the hub.

### Work on a Godot scene or script

In web Chat or Cockpit, choose **Files** and open a `.tscn` scene, a `.gd`
script or `project.godot` (UTF-8, up to 1 MiB). Browse the source pages,
select the passage you want to share and send it with your question.
For example, attach a node's scoring function and ask how it sets the score.
The browser reads the file locally. The selected agent receives your excerpt
when you send the message.

For an editable result, ask for a full script in a `gdscript` code block or a
scene in a `tscn` block. Use **Download Godot script** or **Download Godot
scene** beneath the code. Review the source and save it under the filename
your project references before opening it in Godot.

### Ask two agents the same question

In web Chat, Cockpit or mobile Chat, choose **Compare agents**. Review the
question, pick two agents and submit it once. Each agent answers separately using
the question and its public role. Local comparisons support Ollama and LM Studio.
The hub requests a direct reply when the local Ollama model supports it.
The built-in Gemini and Claude routes also require your permission in the dialog
and approval under the hub's cloud policy. Closing the comparison returns you to
your original chat draft.

To keep one answer, choose **Save to Obsidian** on its card. The note includes
the question, the selected agent, its answer, and any reported model and route.
Review the vault and inbox, edit the title or text, then choose **Save note**.
The confirmation shows the Markdown path. On mobile, **Open saved note** on
that agent’s card reads the latest copy from the original vault.

### Following parallel tasks

In Chat or Cockpit, choose **Create task** underneath a message or a finished
reply. Select a board, edit the title and description, and confirm. The card
appears in **Triage**, where you can review and assign it.

Open **Projects** to see which agents are working on the selected board. Select
a task in **Active workers** to open its history. With two worker slots enabled,
you can approve a second agent's task while the first agent is still working.
The total and per-agent limits also apply to these later approvals. When several
tasks share a prerequisite, open its **Child results** section to read their
outputs together. Selecting a child's title opens its own history.

When a worker finishes, its card shows the recorded result. If the worker only
left a run summary, the card labels it. Open the card for the full text.

Choose **Discuss result in Chat** on a completed card, or **Board result** in
Chat or Cockpit. Review the recorded result, select a passage or attach the
whole result. To compare two workers’ findings, open **Board result** again,
add a passage from the second task and send one question to the selected agent.
You can include up to eight tasks from different boards. Each passage keeps its
board, task ID and result or summary label. The composer rechecks every source
when you send. If a task has changed, review its current output or remove it
before sending the remaining passages. An agent that can use a cloud model needs
your consent to receive the passages.

To keep the selected passages in your vault, choose **Save results to Obsidian**.
The preview checks each source against the board and includes its content
fingerprint. Edit the title and text, then save to the connected vault inbox.
You can do this with an empty chat draft. Saving calls no model.

The saved question includes a link to each source. Open a link after reopening
the chat to see the current result on the original board. If the task output has
changed, the source viewer labels the new version. The saved citation contains
the board, task ID, result type and content fingerprint. Reading a citation
requires owner access and leaves your draft in place.

### ANDREI OS — J.A.R.V.I.S. Second Brain & 3D Workshop (`apps/jarvis-os/`)

A 3D knowledge galaxy over an Obsidian vault plus this repo's own docs, a chat HUD, and a 3D
workshop. It runs two ways from one set of files:

- **Inside the hub — http://127.0.0.1:8080/os/.** The hub serves the interface next to the V2
  cockpit. Chat goes through the hub's orchestrator (`/chat`, with its guards and approval gates;
  matching vault notes ride along as fenced attachments), speech through `/tts`, and the vault graph
  through user-guarded `/api/os/*` routes. Point it at a vault with `JARVIS_OS_VAULT_PATH`; without
  one it shows the demo galaxy. To teach an agent a workflow from a single reply in Chat
  or Cockpit, select **Teach skill**, give the procedure a description, and edit its steps.
  Follow the review link to read and approve the saved version. In a new chat with that
  agent, choose the procedure from **Skills** in the HUD or **Commands → Skills**
  in mobile Chat. When several skills are available, search by words from their
  names. The selection keeps your task in the editor until you send it. Changing
  agents drops the selected skill and keeps the task text. To correct a procedure
  you taught from a reply, open **Skills → Edit steps** in Chat or Cockpit. Submit
  your changes and follow the review link to compare the steps. Once approved
  and applied, the same skill uses the new steps in a fresh chat. For a review of the
  whole conversation, open **Skills → Review this conversation** in the HUD,
  add a focus if needed, and send.
- **Standalone — http://localhost:4719.** A zero-dependency Python 3.9+ server (stdlib
  `ThreadingHTTPServer`, loopback only) with its own multi-provider chat router, sharing nothing
  with the hub's runtime:

```bash
make jarvis-os                      # macOS / Linux → http://localhost:4719
python3 apps/jarvis-os/server.py    # the same, without make
npm run jarvis-os                   # any OS with uv (uv run --no-project --python 3.12 ...)
apps\jarvis-os\START.bat            # Windows: uv → py -3 → python, opens the browser
```

Standalone, `JARVIS_PORT` overrides the port (default `4719`; the hub reads the same variable for
its own port, so leave it unset in a shell that starts both). The vault is auto-detected at
`~/Documents/Andrei OS Obsidian` (demo mode without one) and the hub docs come from the enclosing
checkout — no paths to configure. `apps/jarvis-os/config.json` (API keys) and
`apps/jarvis-os/vault/` are gitignored. Vault files are read without following any symlink or junction, and
hard-linked files are skipped unless `JARVIS_OS_ALLOW_HARDLINKS=1` (needed for a vault in a Google Drive
synced folder); see [`apps/jarvis-os/README.md`](apps/jarvis-os/README.md).

Standalone routes (the hub serves the vault ones as `/api/os/status`, `/api/os/brain`,
`/api/os/brain/note`, `/api/os/brain/retrieve` and `POST /api/os/brain/capture`):

| Route | Method | Purpose |
|---|---|---|
| `/api/status` | GET | Providers, active engine, resolved `vaultPath` / `nervaPath` |
| `/api/brain` | GET | Knowledge graph: nodes, edges, categories, top hubs |
| `/api/brain/note` | GET | First 6,000 characters of an indexed Markdown note (`?relPath=`) |
| `/api/brain/capture` | POST | Write a note into the vault's `08 Inbox/` |
| `/api/config` | POST | Save settings to `config.json` |
| `/api/claude/login` | POST | Start the Claude Code CLI subscription sign-in |
| `/api/chat` | POST | Vault-grounded chat through the provider chain |
| `/api/tts` | POST | ElevenLabs speech, or browser-speech fallback |

Details: [`apps/jarvis-os/README.md`](apps/jarvis-os/README.md).

## Docs

- **`docs/FEATURES.md`** — the one-page product sheet: every feature that ships today, how to install, and what's next on the road to 1.0.
- **`MOONSHOT.md`** — the north star: vision, principles, phase gates, and how the project stays on track. Read this first for the *why* and *where we're going*.
- **`NERVA_VISION.md`** — the Nerva product & capability vision: the brand architecture (Cortex/Atlas/Synapse/Vision/Ultron), the six pillars (perception, communication, action, house, media, capability evolution), the target architecture, the capability registry, graduated autonomy, and the measurable "superior to Hermes" bar.
- **`docs/ARCHITECTURE.md`** — AI-navigable map of the codebase (entry points, request lifecycle, module index, how-to recipes). Start here to find where things live.
- **`docs/AI_CONTEXT.md`** — context-loading map for large-context AI (what to load, in which order, per-task bundles with token estimates).
- **`docs/OWNER_TASKS.md`** — the human-gated queue: everything only the owner can do (hardware runs, GitHub settings, decisions).
- **`docs/RELEASE.md`** — how a release is cut (tag → source bundle + SBOM + checksums + optional signatures) and how to verify a download.
- **`SECURITY.md`** · **`docs/THREAT_MODEL.md`** · **`docs/PRIVACY.md`** — the trust trio: disclosure policy, what Jarvis defends against (with the mechanism for each threat), and the local-first data/telemetry stance.
- **`docs/USER_GUIDE.md`** · **`docs/FAQ.md`** · **`docs/UPGRADE.md`** — the user docs: install/run/daily-use, quick answers, and how to upgrade safely.
- **`NERVA.md`** — architecture & directory structure · **`AGENTS.md`** — assistant conventions · **`BACKLOG.md`** — priorities & tasks.
- **`GO_LIVE_PLAN.md`** — features + marketing brief + v1.0 launch checklist · **`docs/VALUATION_AND_PRICING.md`** — valuation, pricing & unit economics.
- **`docs/MANUAL_TESTING.md`** — human pre-release checklist: everything the offline test suite can't verify (real LLMs, channels, services, HUD rendering).
- **`docs/2026-06-08-future-developments-report.md`** — forward roadmap: remaining v1.0 gate, WorldView follow-ups, audit-debt hardening, post-1.0 horizons (Hermes, Cognition), and recommended sequencing.

## Status

<!-- project-status:readme-status:start -->
Generated status: **v1.0.0** · backend **37,908** · frontend **5,011** · mobile **522** · **940** routes · **17** active agents · open release gates: **A1, A3, A4, A6** · backlog: **289 done · 25 open or blocked of 314 horizon rows** (proof status: [`docs/OWNER_TASKS.md`](docs/OWNER_TASKS.md) → Production-verification checklist) · source commit `02334d9a3fb4`. Full data: [`project-status.json`](project-status.json).
<!-- project-status:readme-status:end -->

**v1.0.0 — the proof track is closed** (the version line is the roadmap — see [BACKLOG.md](BACKLOG.md#version-roadmap): productionization done, the 72h soak now grades itself, design partners running on non-owner installs, owner-host proof passed. The AI-OS capability program, [`NERVA_VISION.md`](NERVA_VISION.md), continues past 1.0 as roadmap rather than as a gate). 17 specialist agents (incl. **Argus** for evidence-based situational awareness and **Howard**, the emerging digital twin; + 14 bench) across 4 tiers; real-embeddings recall (LM Studio) + fused recall +
RAG injection; hot-path perf (SQLite WAL, event-loop offload, checkpoint debounce, query-embedding
cache, complexity-based model tiering); autonomous proactive cortex (ORIZONT 6); security wedge (encrypted
secrets, signed skills, reversible/irreversible approval split, quarantine/capability/kill-switch); competitive edge
(workflow engine, model arena, quality monitor, review queue); living memory (bi-temporal KG, decay-forgetting,
sleep-time consolidation). **Full offline test suite green** — current counts auto-synced in [STATUS.md](STATUS.md) (+ frontend JS tests).

**Road to v1.0:** the original feature backlog (H1–H17) is **code-complete at 194/196 items (≈99% by story points)** —
the only two open items (H12.14 fine-tuned agentic model, H13.3 speculative decoding) need the GPU host
(runbook: `docs/GPU_RUNBOOK.md`). What stands between `0.11.0` and the `1.0.0` tag is now two-fold:
**(a) the proof track** — the **productionization layer** (H23: agentic-safety budgets, DB migrations,
backup/restore + export-delete, operability, quality + user docs — see the
[version roadmap](BACKLOG.md#version-roadmap)) proven with real design-partner users — **and (b) the
AI-OS capability program** (ORIZONT 27–33: capability registry, computer/browser operator, media
director, capability acquisition, ambient intelligence; house brain and cameras were
removed 2026-11-25 —
[`NERVA_VISION.md`](NERVA_VISION.md), gate expanded 2026-07-11); manual testing
([`docs/MANUAL_TESTING.md`](docs/MANUAL_TESTING.md)) + code audit
([`docs/AUDIT.md`](docs/AUDIT.md)) are the release step that tags a version. The HUD V2 cockpit is the default UI;
deep write-controls for ~37 newer backend surfaces are tracked in
[`docs/design/HUD_V2_REMAINING.md`](docs/design/HUD_V2_REMAINING.md). See
[BACKLOG.md](BACKLOG.md#status-general) + [MOONSHOT.md](MOONSHOT.md) §4.

See `STATUS.md`, `BACKLOG.md`, and `docs/ARCHITECTURE.md` for details.
