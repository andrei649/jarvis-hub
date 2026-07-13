# Jarvis mobile

A native iOS & Android companion app for the Jarvis hub, built with
[Expo](https://docs.expo.dev/) (SDK 57 / React Native 0.86).

It talks to the same HTTP API the web HUD uses (`agents/web.py`):

- **Chat** — streaming conversation over `POST /chat/stream` (server-sent
  events, rendered token-by-token). Assistant replies render **Markdown**
  (code blocks, lists, bold/italic, links). Pick the **agent** (`GET /api/agents`),
  tap 🔊 to hear a reply via **TTS** (`POST /tts`), and **Stop** mid-stream.
  The thread is **persisted on-device** and survives restarts.
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
