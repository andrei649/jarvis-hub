# GEMINI.md — Project Context & Handoff Guide (macOS & Windows)

This workspace contains **ANDREI OS / AI WORKSHOP OS — J.A.R.V.I.S.**, an interactive 3D Second Brain, Multi-Platform AI Hub, 3D CAD Workshop, and Computer Use HUD running on `http://localhost:4719`.

## Architecture & Key Files
- `server.py`: Zero-dependency Python 3 (`3.9+` / `3.12`) multi-threaded HTTP & JSON server (`127.0.0.1:4719`).
  - Auto-detects the Second Brain vault across macOS and Windows (`./vault/Andrei OS Obsidian` or `~/Documents/Andrei OS Obsidian`) plus the `Nerva / Jarvis Hub` docs: the app lives at `apps/jarvis-os/` inside the `jarvis-hub` repo and finds that enclosing checkout by walking up `ROOT_DIR.parents` (fallbacks: `~/Documents/Nerva/jarvis-hub`, `./jarvis-hub`).
  - `config.json` (API keys), `vault/` and `*.zip` bundles are gitignored — never commit them.
  - Provides `/api/brain`, `/api/brain/note`, `/api/brain/capture` (writes new notes to `08 Inbox/`), `/api/status`, `/api/config`, `/api/claude/login`, `/api/chat`, and `/api/tts`.
  - **Unified Multi-Platform AI Router**: Supports Anthropic Subscription via Claude Code CLI (`claude -p --model fable|sonnet`), Local Ollama (`http://127.0.0.1:11434`), Anthropic API, OpenAI API, Google Gemini API, OpenRouter / LM Studio (e.g. Bonobo RTX 5090), and grounded Vault RAG synthesis.
- `START.bat`: One-click Windows launcher.
- `export_for_windows.py`: Packages a clean, secret-free portable `.zip` bundle (including `vault/Andrei OS Obsidian`) for moving between macOS and Windows.
- `public/index.html` & `public/css/styles.css`: Glassmorphic UI with clean homescreen sidebar (`ANDREI OS`) and dedicated tabbed `⚙️ Settings` modal (`AI Connections`, `Second Brain Vaults`, `Visual Customizations`).
- `public/js/main.js`, `public/js/galaxy.js`, `public/js/brain-data.js`, `public/js/jarvis-hud.js`, `public/js/agent-engine.js`, `public/js/workshop-robot.js`, `public/js/workshop-house.js`, `public/js/computer-use.js`.

## Served by the Nerva hub too
- The hub serves this same `public/` at `http://127.0.0.1:8080/os/` (`agents/core/routers/jarvis_os.py`), loading the vault indexer from `server.py`.
- `public/js/api.js` is the single place that calls a backend; keep every `fetch` there. Asset URLs stay relative and three.js stays vendored (`public/vendor/three/`) — the hub's CSP blocks CDNs.

## Security rules to keep
- Standalone chat defaults to Ollama/offline vault synthesis. `cloudConsent` must
  be exactly JSON `true`, both when the request starts and at every remote dispatch;
  credentials, CLI login and legacy `auto` never grant consent. Keep the late
  post-probe revocation checks, local model provenance, fully tagged `:local`
  selector and proxy/redirect refusal. Unknown/older model runtimes fail offline;
  never retry with an unrestricted model name. Hub `/os` uses separate `/chat` policy.
- Vault and repo files are read, and inbox notes created, only through `vault_fs.py` (handle-relative, no symlink/junction followed, hard links refused unless `JARVIS_OS_ALLOW_HARDLINKS=1`). Never add a `Path.read_text` / `open(path)` on a vault path, and never add a path-based fallback.
- `/api/brain/note` is an allowlist of Markdown the graph indexed (`read_indexed_note`). Do not turn it back into a path check.
- Untrusted text reaches the DOM only through `public/js/templates.js` (escaped). No raw `${...}` of vault, model or server text inside an `innerHTML` template.
- The standalone server sends no CORS headers and checks `Origin` and `Host` on `/api`.

## Running Locally
- **Windows**: Double-click `START.bat` (tries `uv run --no-project --python 3.12 python server.py`, then `py -3`, then `python`), or `npm run jarvis-os` from the repo root.
- **macOS / Linux**: `make jarvis-os` from the repo root, or `python3 server.py` here.
- Open `http://localhost:4719` in Chrome, Edge, or Safari.
