# ANDREI OS — J.A.R.V.I.S. Second Brain & 3D Workshop

Interactive local **J.A.R.V.I.S. Second Brain + Unified Multi-Platform AI Hub + 3D Workshop** (`http://localhost:4719`).

## Quick Start

This app lives in the `jarvis-hub` repository at `apps/jarvis-os/` and runs two ways.

**Inside the Nerva hub** — start the hub (`python serve.py`) and open
**http://127.0.0.1:8080/os/**. The hub serves `public/` itself and the page talks to the hub: chat
goes through the hub's orchestrator (`/chat`). Select **Include matching notes** to attach
excerpts to the next message. Speech uses the hub's `/tts` and the graph comes from `/api/os/*`. The provider
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

## Standalone chat privacy and migration

Chat defaults to **local Ollama, then an offline vault answer**. The separate
**Allow cloud chat** checkbox in Settings is off by default, including for old
`auto` configurations. API keys, a signed-in Claude CLI, or selecting a provider
do not grant consent. Set `"cloudConsent": true` as a JSON boolean or check the
box and save to permit sending prompts, UI context and retrieved vault notes to
cloud providers. Strings such as `"true"` and unknown providers fail safely.

`auto` now tries Ollama first, then the cloud chain only with consent. A selected
cloud provider also requires consent; otherwise chat falls back locally. Remote
Ollama URLs require consent too; local model POSTs bypass inherited HTTP proxies
and refuse redirects. Custom OpenAI-compatible endpoints use the cloud gate even
when configured on loopback. Select `ollama` to avoid fallbacks to other providers. Ollama cloud models also
require consent, even when its daemon runs on loopback. Disable consent and save to stop future cloud chat dispatches.
Consent is rechecked before later cloud fallbacks in an in-progress request;
already dispatched requests are not recalled.

Without consent, Ollama candidates require local artifact metadata, refreshed
before each prompt. Cloud aliases and unknown metadata are skipped. Requests pin
an explicit `:local` source selector (Ollama 0.18+), which refuses a model that
has become a remote alias. Older daemons may reject this selector and use the
offline fallback; the app never retries without it. A loopback daemon remains a
trusted local service. See [Ollama cloud authentication](https://github.com/ollama/ollama/blob/main/docs/api/authentication.mdx)
and its [local-source refusal](https://github.com/ollama/ollama/blob/v0.18.0/server/routes.go#L1992).

Blank or `***` key fields preserve saved secrets on settings saves. To remove a
key, remove it from the private `config.json` and its corresponding environment
variable. This chat consent setting does not govern the separate ElevenLabs speech
action. Hub `/os` uses the hub's `/chat` and its own policy; these standalone
settings do not apply there.

## Paths, secrets and the vault

In the hub HUD, open **Chat**, type a question and select **Vault**. Review the excerpts,
check the ones to include and send. The hub checks the selection against the current vault
before sending. The conversation lists the sources attached to that turn.

For a scoped vault, put the following settings in the hub checkout's private `.env`.
Use the absolute path to your own vault and its existing inbox. The example also reads
a compact project register. Its rows appear in the graph and in searches with a
source reference ending in the project ID.

```dotenv
JARVIS_OS_VAULT_PATH="C:/path/to/My Vault"
JARVIS_OS_VAULT_INCLUDE="Journal/Inbox;Projects/index.json"
JARVIS_OS_VAULT_INBOX="Journal/Inbox"
JARVIS_OS_PROJECT_INDEX=1
JARVIS_OS_REPOSITORY_DOCS=0
```

Include and exclude paths are relative to the vault and separated by semicolons.
`NERVA_OS_VAULT_EXCLUDE` takes precedence over included paths. The index reader
uses the validated `project-index/v1` file directly. Set `JARVIS_OS_PROJECT_INDEX_PATH`,
`JARVIS_OS_PROJECT_REGISTER_DIR` and `JARVIS_OS_PROJECT_INDEX_SCHEMA` in the private
`.env` if an existing index uses different vault-relative locations or a different schema tag.
The index path must also be in `JARVIS_OS_VAULT_INCLUDE`. For a register
row with an existing note, **Open in Obsidian** opens that note in
your registered vault. The register supplies the searchable project summary.
Including the register alone does not add project note bodies to search.
The compact JSON shape is `{"schema":"project-index/v1","items":[{"id":"PRJ-123","n":"Garden.md","pas":"Plant seeds"}]}`;
`n` names a Markdown file in the register directory, and `pas` is an optional next step.
[Obsidian URI reference](https://obsidian.md/help/uri)

In chat, open **Vault** and search using your draft. Check an excerpt to attach
it. For a readable note, **Choose passage** shows up to the first 6,000 characters.
Highlight up to 1,500 characters, choose **Use selected passage**, and review the
text before sending. The hub rechecks the source when you send. A source link
alone opens the note in Obsidian without attaching any text.

Each capture creates a new file in the configured inbox. The default folder for a legacy vault is
`08 Inbox`. Markdown with a private, restricted or unrecognized privacy value is
hidden from the graph, direct reads, and retrieval. Unreadable or ambiguous headers
are skipped. For standalone mode, set `vaultPath`, `vaultInclude`, `vaultExclude`,
`vaultInbox`, `projectIndex`, `projectIndexPath`, `projectRegisterDir`,
`projectIndexSchema` and `vaultMode` in the private `apps/jarvis-os/config.json`.
Use `"andrei_os"` to display only the vault.

- **Vault** — auto-detected in this order: `apps/jarvis-os/vault/Andrei OS Obsidian`,
  `~/Documents/Andrei OS Obsidian`, then a sibling `Andrei OS Obsidian` folder. With no vault on
  disk, `/api/brain` answers in `demo_550` mode.
- **Nerva / Jarvis Hub docs** — the enclosing `jarvis-hub` checkout is detected by walking up from
  this folder, so no path needs configuring on either OS.
- **`config.json`** (API keys, written by ⚙️ Settings) and **`vault/`** are gitignored, and so are
  the `*.zip` bundles `export_for_windows.py` produces. Copy `config.example.json` to `config.json`
  only if you want to pre-seed settings; leave `vaultPath` / `nervaPath` empty for auto-detection.

## What the app will and will not touch

- **No link is followed.** Every read and every create under the vault goes through
  `vault_fs.py`: each path component is opened relative to its parent's handle (`openat` with
  `O_NOFOLLOW` on macOS/Linux, `NtCreateFile` with a `RootDirectory` handle on Windows). A
  symlink, a junction, or a folder swapped mid-request is refused, never followed. There is no
  path-based fallback on any platform.
- **Hard links are skipped by default.** A file with more than one hard link may be a second
  name for something outside the vault. Skipped entries are counted in `/api/brain` (`skipped`)
  and shown in Settings, so a thinner graph is explained. Google Drive hard-links a file while
  it uploads it; if your vault lives in a Drive-synced folder and notes go missing, set
  `JARVIS_OS_ALLOW_HARDLINKS=1` (or `"allowHardLinks": true` in `config.json`).
- **Reparse points are refused on Windows**, which includes OneDrive online-only placeholders.
- **The note route is an allowlist.** `/api/brain/note` serves only Markdown that the graph
  itself indexed: never `config.json`, `.env`, or a `*.local.md`.
- **Capture never overwrites and never leaves the inbox.** A duplicate title becomes
  `<title> (2).md`. The capture refuses linked inbox directories before writing.
- **Only this page may call the API.** The standalone server sends no CORS headers and refuses
  requests whose `Origin` or `Host` is not its own.

## Frontend notes

Open **Artifacts → Open 3D workshop** in the hub, or visit `/os/?studio=house`
for the house. **Edit with AI** sends a material or layout request to the hub’s
local model. For example, ask it to set the robot shell to `#7359ae` or widen
the kitchen by 1.25 metres. The result changes the scene in the open tab.

Open **Projects**, name the scene and save a version to keep editing later.
Each save creates a Markdown note in the configured Obsidian inbox, with a
readable summary, editable scene settings and camera position. The project link
reopens that version. Uploaded reference pictures stay in the current tab.
In the HUD, **Artifacts → Saved 3D projects** opens a version or brings it into
chat for review. To hand it to a task, open its comments, select **Link a saved
3D project**, review the draft, then post.

**Blender / Godot (.glb)** downloads the visible model with named parts,
materials and embedded textures. The miniature also includes its desert scenery.
In Blender choose **File → Import → glTF 2.0**, select the download, then save
the project as a `.blend` file. For Godot, drop the same file into the project's
FileSystem dock and add the imported scene to a level. The workshop also accepts
“Export this model for Godot”. [Godot asset import](https://docs.godotengine.org/en/stable/tutorials/assets_pipeline/import_process.html)

For a 1:100 house floor plan, download the SVG or choose **Illustrator script
(.jsx)**. You can also ask the workshop to “Export my floor plan for
Illustrator”. In Illustrator, choose **File → Scripts → Other Script**, open
the downloaded JSX, then use **Save As** to keep the new drawing as an `.ai`
file. Rooms, walls, pools and labels remain editable. [Running scripts in Illustrator](https://helpx.adobe.com/illustrator/desktop/automate-visualize-data/automate-actions/install-and-run-scripts.html)

- `public/js/templates.js` builds every piece of HTML that contains text the page does not own
  (note titles, paths, model names, a model's action parameters) and escapes all of it.

- `public/js/api.js` is the only file that calls a backend. It picks the hub or the standalone
  routes from the `<meta name="jarvis-os-hub">` tag the hub adds to the page.
- three.js 0.169.0 (MIT) is vendored under `public/vendor/three/`, and asset URLs are relative, so
  the page works under the hub's Content-Security-Policy and at any base path.

## API

Standalone routes are listed below. The hub exposes the vault through `/api/os/status`,
`/api/os/brain`, `/api/os/brain/note`, `/api/os/brain/retrieve` and
`POST /api/os/brain/capture`. Workshop edits use `POST /api/os/workshop/edit`.

The hub's note search ranks the full body of each eligible Markdown note and
returns up to four matching excerpts, each at most 1,500 characters. Its note
reader accepts the same question in `q` to open a 6,000-character window around
a late match. A nonzero `start` gives the window's zero-based character offset.
Omit `q` for the opening of the note.

| Route | Method | Purpose |
|---|---|---|
| `/api/status` | GET | Providers, active engine, resolved `vaultPath` / `nervaPath` (`?refresh=1` re-probes) |
| `/api/brain` | GET | The knowledge graph: nodes, edges, categories, top hubs (`?reindex=1` rebuilds) |
| `/api/brain/note` | GET | First 6,000 characters of an indexed Markdown note (`?relPath=...`) |
| `/api/brain/capture` | POST | Write a new note into the configured vault inbox |
| `/api/workshop/projects` | GET, POST | List saved versions or save a new version in the vault inbox. Hub prefix is `/api/os`. |
| `/api/workshop/project?path=…` | GET | Read one saved version and its summary. Hub prefix is `/api/os`. |
| `/api/config` | POST | Save settings to `config.json` |
| `/api/claude/login` | POST | Start the Claude Code CLI subscription sign-in |
| `/api/chat` | POST | Vault-grounded chat through the provider chain |
| `/api/tts` | POST | ElevenLabs speech, or a browser-speech fallback without a key |

## Key Capabilities

1. **Real Second Brain ("Andrei OS Obsidian" + "Nerva / Jarvis Hub")**
   - Automatically indexes `~/Documents/Andrei OS Obsidian` (Markdown notes, YAML frontmatter, `.canvas` visual maps, and `[[wiki-links]]` across `00 Acasa` through `90 Atasamente`) plus the docs of the enclosing `jarvis-hub` repository.
   - Click a note to read it in `INSPECTOR`, **Shift-click** another node to trace the shortest link path, or save a note to the configured inbox.
   - Switch anytime in **⚙️ Settings → Second Brain Vaults** between `Andrei OS + Nerva`, `Andrei OS Only`, and the `550-node Video Showcase Demo`.

2. **Unified Multi-Platform AI Hub (`⚙️ Settings → AI Connections`)**
   - **Anthropic Subscription (Claude Code CLI `claude -p`)**: Optional cloud connector requiring explicit cloud chat consent. Click **Sign in with Claude Subscription** in Settings to authenticate via browser OAuth; sign-in alone does not enable chat dispatch.
   - **Local Ollama Runtime**: Auto-detects local models (`qwen3.5:4b`, `qwen3.5:0.8b`) at `http://127.0.0.1:11434` for immediate on-device private chat + RAG.
   - **Cloud & Custom Connectors**: Ready for Anthropic Console API, OpenAI/ChatGPT, Google Gemini, OpenRouter / Bonobo RTX 5090 LM Studio, and ElevenLabs TTS.

3. **Clean Homescreen + Dedicated `⚙️ Settings` Drawer**
   - Keeps the main galaxy homescreen focused on Search, Inspector, and Top Hubs while housing all **3D Galaxy Forces**, **Render Layers**, **Color Themes**, and **HUD Visibility Toggles** inside **⚙️ Settings → Visual Customizations**.

4. **3D Workshop (Robot Chassis, Pool Home & Miniature) & Computer Use**
   - Voice/text-driven `Jarvis Reactor Companion` with PBR materials and **Exploded View** callouts.
   - The Pool Home studio lets you remodel the bundled house and switch to its miniature diorama. Choosing a floor-plan image updates the visual reference beside the scene.
   - Autonomous **Meta Ads Manager** Computer Use driver + live browser tab screen-sharing.
