# ANDREI OS — J.A.R.V.I.S. Second Brain & 3D Workshop

Interactive local **J.A.R.V.I.S. Second Brain + Unified Multi-Platform AI Hub + 3D Workshop** (`http://localhost:4719`).

## Quick Start

This app lives in the `jarvis-hub` repository at `apps/jarvis-os/` and runs two ways.

**Inside the Nerva hub** — start the hub (`python serve.py`) and open
**http://127.0.0.1:8080/os/**. The hub serves `public/` itself and the page talks to the hub: chat
goes through the hub's orchestrator (`/chat`), with the matching vault notes attached as fenced
content; speech uses the hub's `/tts`; the vault graph comes from `/api/os/*`. The provider
settings below do not apply there, so the AI Connections tab is hidden. Set
`JARVIS_OS_VAULT_PATH` if the vault is not at `~/Documents/Andrei OS Obsidian`.

**Standalone** — a zero-dependency Python 3.9+ server (stdlib only) with its own provider router,
separate from the hub:

```bash
# macOS / Linux — from the repo root
make jarvis-os                      # or: python3 apps/jarvis-os/server.py

# Windows — double-click apps\jarvis-os\START.bat, or from the repo root
npm run jarvis-os                   # uv run --no-project --python 3.12 python apps/jarvis-os/server.py
```

`START.bat` tries `uv` first, then `py -3`, then `python`, so it still works when `python.exe`
is only the Microsoft Store stub. Set `JARVIS_PORT` to use a port other than `4719`.

Open **http://localhost:4719** in Chrome, Edge, or Safari.

## Paths, secrets and the vault

- **Vault** — auto-detected in this order: `apps/jarvis-os/vault/Andrei OS Obsidian`,
  `~/Documents/Andrei OS Obsidian`, then a sibling `Andrei OS Obsidian` folder. With no vault on
  disk, `/api/brain` answers in `demo_550` mode.
- **Nerva / Jarvis Hub docs** — the enclosing `jarvis-hub` checkout is detected by walking up from
  this folder, so no path needs configuring on either OS.
- **`config.json`** (API keys, written by ⚙️ Settings) and **`vault/`** are gitignored, and so are
  the `*.zip` bundles `export_for_windows.py` produces. Copy `config.example.json` to `config.json`
  only if you want to pre-seed settings; leave `vaultPath` / `nervaPath` empty for auto-detection.

## Frontend notes

- `public/js/api.js` is the only file that calls a backend. It picks the hub or the standalone
  routes from the `<meta name="jarvis-os-hub">` tag the hub adds to the page.
- three.js 0.169.0 (MIT) is vendored under `public/vendor/three/`, and asset URLs are relative, so
  the page works under the hub's Content-Security-Policy and at any base path.

## API

Standalone routes. In the hub the vault routes are `/api/os/status`, `/api/os/brain`,
`/api/os/brain/note`, `/api/os/brain/retrieve` and `POST /api/os/brain/capture`.

| Route | Method | Purpose |
|---|---|---|
| `/api/status` | GET | Providers, active engine, resolved `vaultPath` / `nervaPath` (`?refresh=1` re-probes) |
| `/api/brain` | GET | The knowledge graph: nodes, edges, categories, top hubs (`?reindex=1` rebuilds) |
| `/api/brain/note` | GET | Full body of one note (`?relPath=...`) |
| `/api/brain/capture` | POST | Write a new note into the vault's `08 Inbox/` |
| `/api/config` | POST | Save settings to `config.json` |
| `/api/claude/login` | POST | Start the Claude Code CLI subscription sign-in |
| `/api/chat` | POST | Vault-grounded chat through the provider chain |
| `/api/tts` | POST | ElevenLabs speech, or a browser-speech fallback without a key |

## Key Capabilities

1. **Real Second Brain ("Andrei OS Obsidian" + "Nerva / Jarvis Hub")**
   - Automatically indexes `~/Documents/Andrei OS Obsidian` (Markdown notes, YAML frontmatter, `.canvas` visual maps, and `[[wiki-links]]` across `00 Acasa` through `90 Atasamente`) plus the docs of the enclosing `jarvis-hub` repository.
   - Click any orb to read the real note in `INSPECTOR`, **Shift-click** a second orb to trace the shortest semantic path, or save new notes straight to `08 Inbox/`.
   - Switch anytime in **⚙️ Settings → Second Brain Vaults** between `Andrei OS + Nerva`, `Andrei OS Only`, and the `550-node Video Showcase Demo`.

2. **Unified Multi-Platform AI Hub (`⚙️ Settings → AI Connections`)**
   - **Anthropic Subscription (Claude Code CLI `claude -p`)**: Primary zero-extra-billing demo connector (`Opus 5.5` → Sonnet/Opus, `Fable 5.2` → Fable/Opus). Click **Sign in with Claude Subscription** in Settings to authenticate via browser OAuth.
   - **Local Ollama Runtime**: Auto-detects local models (`qwen3.5:4b`, `qwen3.5:0.8b`) at `http://127.0.0.1:11434` for immediate on-device private chat + RAG.
   - **Cloud & Custom Connectors**: Ready for Anthropic Console API, OpenAI/ChatGPT, Google Gemini, OpenRouter / Bonobo RTX 5090 LM Studio, and ElevenLabs TTS.

3. **Clean Homescreen + Dedicated `⚙️ Settings` Drawer**
   - Keeps the main galaxy homescreen focused on Search, Inspector, and Top Hubs while housing all **3D Galaxy Forces**, **Render Layers**, **Color Themes**, and **HUD Visibility Toggles** inside **⚙️ Settings → Visual Customizations**.

4. **3D Workshop (Robot Chassis, 2D Floor Plan → 3D Villa & Miniature) & Computer Use**
   - Voice/text-driven `Jarvis Reactor Companion` with PBR materials and **Exploded View** callouts.
   - `Pool Home Plan` 2D-to-3D architectural studio with live remodeling and golden-hour **Miniature** diorama renderer.
   - Autonomous **Meta Ads Manager** Computer Use driver + live browser tab screen-sharing.
