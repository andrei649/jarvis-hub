# Jarvis mobile

A native iOS & Android companion app for the Jarvis hub, built with
[Expo](https://docs.expo.dev/) (SDK 56 / React Native 0.85).

It talks to the same HTTP API the web HUD uses (`agents/web.py`):

- **Chat** — streaming conversation with Jarvis over `POST /chat/stream`
  (server-sent events, rendered token-by-token).
- **Status** — live view of `GET /status`: model state, backend, agents
  online, and host/GPU telemetry, with pull-to-refresh.
- **Settings** — point the app at any hub (`http://<host>:<port>`), set an
  optional `JARVIS_USER_TOKEN`, and test the connection. Settings persist
  on-device via AsyncStorage.

## Run it

```bash
cd mobile
npm install
npx expo start          # then press i / a, or scan the QR code with Expo Go
```

On a phone you'll need the hub reachable on your network. In **Settings**
enter the hub address (e.g. `192.168.1.20:8000`) — the `http://` scheme is
added automatically. If the hub has `JARVIS_USER_TOKEN` set, enter the same
value as the user token; it is sent as the `X-User-Token` header.

> Cleartext HTTP to a LAN hub is enabled (`NSAllowsLocalNetworking` on iOS,
> `usesCleartextTraffic` on Android) so a local, unsecured hub works out of
> the box. Use a token (and ideally TLS via a reverse proxy) for anything
> exposed beyond localhost.

## Layout

```
App.tsx                     root shell + bottom tabs
src/theme.ts                HUD-derived color palette
src/context/ServerContext   connection config (loaded/persisted)
src/storage/settings.ts     AsyncStorage read/write
src/api/client.ts           fetch + XHR SSE streaming client
src/screens/                Chat / Status / Settings
src/components/              MessageBubble
```

## Build

Use [EAS Build](https://docs.expo.dev/build/introduction/) for store-ready
binaries:

```bash
npx eas build -p ios
npx eas build -p android
```
