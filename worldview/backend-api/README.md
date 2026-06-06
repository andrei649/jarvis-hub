# WorldView Backend API

Node.js / **Fastify** service that powers the 4D Playback Engine: REST endpoints serving
**historical state** from TimescaleDB (as-of-T reconstruction) and a **WebSocket** stream
serving **live state** from Redis (snapshot + pub/sub deltas).

## Status

STEP 2 scaffold — Fastify bootstrap with `/health`, CORS, the WebSocket plugin registered,
and lazy Redis (`ioredis`) + TimescaleDB (`pg`) connection factories. The actual
`/history` REST routes and `/live` WebSocket telemetry are implemented in **STEP 4**.

## Develop

```bash
npm install                    # from worldview/ root (workspaces)
cp .env.example .env
npm run dev --workspace backend-api   # http://localhost:4000/health
```

## Layout

```
src/server.ts        Fastify bootstrap (buildServer + main)
src/config.ts        env-derived config
src/routes/          health.ts now; history.ts + live.ts in STEP 4
src/plugins/         redis.ts (live cache) + db.ts (TimescaleDB pool)
```
