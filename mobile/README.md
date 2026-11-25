# Jarvis mobile

A native iOS & Android companion app for the Jarvis hub, built with
[Expo](https://docs.expo.dev/) (SDK 58 / React Native 0.88).

The app uses the same hub API as the web HUD. The bottom bar opens Chat, Tasks and Skills. Tap **More** for the other
destinations, including Settings, Memory and Approvals.

- **Chat** — streaming conversation over `POST /chat/stream` (server-sent
  events, rendered token-by-token). Assistant replies render **Markdown**
  (code blocks, lists, bold/italic, links). Pick the **agent** (`GET /api/agents`),
  tap 🔊 to hear a reply via **TTS** (`POST /tts`), and **Stop** mid-stream.
  When the hub reports which models it called, their provider and model names appear
  below the reply. The thread and its recorded calls survive restarts on the same connection.
  **Agent tool calls recorded** shows how many tool executions the hub observed for that
  reply. A zero means the hub recorded no agent tool execution. A delivery confirmation
  comes from the messaging service itself.
  In **Commands → Skills**, select an approved skill for the current agent.
  Search by name when the agent has several skills. Your task stays in the
  editor until you tap **Send**. Switching agents keeps the task text.
  While a local model prepares its first token, the hub sends a keepalive every 15 seconds.
  The mobile client reports a stalled stream after 45 seconds without incoming bytes.
  For a short question, choose **Send direct reply** to ask a supported model to
  skip extended thinking for that message. To keep a fact for future owner chats,
  tap **Remember message** under your own message. Edit the copy, choose **Agent notes**
  or **User profile**, then tap **Save fact**. Saving uses the owner access configured
  for this chat. To update an older preference, tap **Replace a saved fact**,
  choose its current wording in that store, and tap **Save correction**.
  To remove a preference, tap **Forget a saved fact**, choose its exact wording
  and confirm. **Undo forget** restores it while the saved facts still match.
  To find an older message, tap **History → Search messages**, enter words from
  the message and submit. Tap **Review source** to read the full saved turn,
  then **Continue this conversation** to reopen that chat. Your typed message
  stays in the composer until you send it. Message search requires owner access.
  To quote it in your current chat, type or paste the exact passage, or tap
  **Use entire message**. Confirm cloud sharing if your selected agent can use
  a cloud model, then tap **Use passage in next message**. You can remove the
  passage before sending. The question keeps a citation after you reopen the app.
  To use the connected Obsidian vault, type a question, tap **Obsidian notes**,
  review the matching excerpts, then choose **Send with notes**. Only the selected
  excerpts go to the agent with that question. If an excerpt changes, review it again.
  Tap **Save to Obsidian** under a completed answer to edit its title and text,
  review the vault and inbox, and save. Tap **Open saved note** to read the
  current version from the hub, including after reopening the app on the same
  cached conversation. **Open in Obsidian on this device**
  uses the phone's local copy when the same vault is available there.
- **Memory** — read-only session memory, notes, and knowledge graph data over
  `GET /memory`, `GET /api/notes`, and `GET /api/kg/*`. The tab has Turns and
  Graph views for recent turns, current notes, graph entities/relations, and
  KG facts/history without exposing clear/save/rewrite/delete controls from the phone.
- **Status** — live view of `GET /status`, `GET /dashboard`, and
  `GET /ticker`: model state, backend, agents online, host/GPU telemetry,
  ambient dashboard counts, live ticker rows, and a read-only Trust card over
  `GET /api/security/{governance,posture,kill-switch,loop-breaker}`, with pull-to-refresh.
- **Approvals** — mobile Decision Inbox over `GET /autonomy/approvals`
  with approve / reject / defer actions posted to
  `POST /autonomy/tasks/{id}/decision`. This uses the same unified approval
  funnel as the browser HUD and requires the hub admin token.
- **Tasks** — read-only mobile task board over `GET /tasks`, showing active,
  waiting, and completed autonomy work with pull-to-refresh. Empty means the
  hub has no current task work; no demo rows are invented.
- **Skills** — read-only mobile skills catalog over `GET /skills`, showing
  discovered skills, versions, assigned agents, and command counts without
  exposing install/import controls from the phone.
- **Comms** — live Safe Comms channel inbox over `GET /api/channels/inbox*`.
  Read telegram/web threads, refresh messages, and queue governed replies to
  `POST /api/channels/inbox/{thread_id}/reply`; the server still sends only
  after the existing approval funnel accepts the task.
- **Media** — metadata-only Media Director parity over `GET /api/media/devices`
  and `GET /api/media/session`, with explicit governed presentation and restore
  actions. Disabled, queued, refused, unverified, and verified outcomes stay
  visually distinct. Owner-curated device registration/removal is isolated in
  an admin-token-gated zone; the app never embeds remote media.
- **Settings** — point the app at any hub (`http://<host>:<port>`), set an
  optional `JARVIS_USER_TOKEN` plus `JARVIS_ADMIN_TOKEN`, and test the connection. Persisted via
  AsyncStorage.
- **History** — resume a previous hub session (`/sessions` → `/sessions/resume`)
  back into the chat thread.

Network calls have request timeouts, retry/back-off on idempotent GETs, and an
idle-timeout on the chat stream so a flaky link never leaves a message hanging.

## Run it

```bash
cd mobile
npm install
npx expo start          # then press i / a, or scan the QR code with Expo Go
```

On a phone you'll need the hub reachable on your network. In **Settings**
enter the hub address (e.g. `192.168.1.20:8000`) — the `http://` scheme is
added automatically. If the hub has `JARVIS_USER_TOKEN` set, enter the same
value as the user token; it is sent as the `X-User-Token` header. To approve
actions from the phone, also enter `JARVIS_ADMIN_TOKEN`; it is sent only as
`X-Admin-Token` for admin-gated routes.

> Cleartext HTTP to a LAN hub is enabled (`NSAllowsLocalNetworking` on iOS,
> `usesCleartextTraffic` on Android) so a local, unsecured hub works out of
> the box. Use a token (and ideally TLS via a reverse proxy) for anything
> exposed beyond localhost.

## Scripts

```bash
npm test                  # Jest — pure logic, API normalization, UI contracts
npx tsc --noEmit          # type-check
node scripts/gen-icons.js # regenerate branded app icons (deterministic, pngjs)
```

## Layout

```
App.tsx                     root shell + bottom tabs
src/theme.ts                HUD-derived color palette
src/context/ServerContext   connection config (loaded/persisted)
src/storage/                AsyncStorage: settings, chat history, prefs
src/api/client.ts           fetch + XHR SSE streaming client (timeouts/retries)
src/api/sse.ts              pure SSE decoder (unit-tested)
src/audio/tts.ts            /tts → cache file → expo-audio playback
src/markdown/               pure Markdown parser (unit-tested) + RN renderer
src/components/             MessageBubble, AgentPicker, SessionsModal
src/screens/                Chat / Memory+Graph / Approvals / Tasks / Media / Comms / Skills / Status / Settings
scripts/gen-icons.js        icon/splash generator
```

## Build (EAS)

Store-ready binaries via [EAS Build](https://docs.expo.dev/build/introduction/);
profiles are in `eas.json` (development / preview / production):

```bash
npx eas build --profile preview     -p android   # internal APK
npx eas build --profile production  -p ios        # store build
```

The first `eas` run links the project to your Expo account (creates the
`projectId`). TestFlight / Play submission uses the `submit` profile.
