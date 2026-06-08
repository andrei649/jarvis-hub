# @worldview/mcp

A [Model Context Protocol](https://modelcontextprotocol.io) (MCP) server that exposes the
**WorldView 4D OSINT platform** as MCP tools, so an MCP client — such as the JARVIS agent
system — can query the platform's space-time history in natural agent workflows.

It is a thin, stateless adapter: each tool calls the existing WorldView REST API
(`@worldview/backend-api`, a Fastify service) over HTTP and returns the GeoJSON it gets back.
This package does **not** talk to the database directly and holds no state of its own.

## Tools

| Tool | Description |
| --- | --- |
| `state_at` | As-of-`t` reconstruction of one layer at a unix timestamp → GeoJSON `FeatureCollection`. Optional `bbox` (`w,s,e,n`) and `lod` (`raw`/`minute`). Backend: `GET /history/:layer`. |
| `find_dark_vessels` | Vessels with suspicious AIS gaps at time `t`. Pulls the derived `context` layer and keeps only `properties.kind === "dark_vessel"` features. Backend: `GET /history/context`. |
| `track_of` | One entity's movement trail (GeoJSON `LineString`) for the `adsb`/`ais`/`tle` layers. Optional `from`/`to` (default: trailing hour). Backend: `GET /history/:layer/:entityId/track`. |
| `list_layers` | Static catalogue of the five layers with one-line descriptions. No network call. |

### Layers

- `adsb` — Aircraft positions from ADS-B transponders. *(trackable)*
- `ais` — Vessel positions from AIS maritime transponders. *(trackable)*
- `tle` — Satellite positions propagated from TLE orbital elements. *(trackable)*
- `ew` — Electronic-warfare / RF emitter detections.
- `context` — Derived overlays (NOTAMs, strike zones, events, dark vessels).

## Configuration

| Env var | Default | Meaning |
| --- | --- | --- |
| `WORLDVIEW_API_URL` | `http://localhost:4000` | Base URL of the WorldView backend REST API. |

## Running

This is a **standalone** package with its own `node_modules` (it is intentionally *not* part of
the `worldview/` npm workspace).

```bash
npm install
npm run typecheck   # tsc --noEmit
npm test            # node:test unit tests (stubbed fetch, no network)
npm run build       # emit dist/
npm start           # run the server over stdio (tsx src/server.ts)
```

## Launching from an MCP client (stdio)

The server speaks the MCP **stdio** transport. A JARVIS-style client launches it as a child
process and communicates over stdin/stdout. Example client config:

```json
{
  "mcpServers": {
    "worldview": {
      "command": "npx",
      "args": ["tsx", "src/server.ts"],
      "cwd": "/path/to/jarvis-hub/worldview/mcp",
      "env": { "WORLDVIEW_API_URL": "http://localhost:4000" }
    }
  }
}
```

Or, after `npm run build`, point the client at the compiled entrypoint:

```json
{
  "mcpServers": {
    "worldview": {
      "command": "node",
      "args": ["/path/to/jarvis-hub/worldview/mcp/dist/server.js"],
      "env": { "WORLDVIEW_API_URL": "http://localhost:4000" }
    }
  }
}
```

stdout is reserved for the JSON-RPC stream; the server logs only to stderr.

## Layout

- `src/config.ts` — reads `WORLDVIEW_API_URL`.
- `src/tools.ts` — pure, testable tool handlers `(args, deps)` with an injectable `fetchImpl`.
- `src/server.ts` — MCP `Server` over `StdioServerTransport`, registering the four tools with
  JSON-Schema input definitions and dispatching to the `tools.ts` handlers.
- `test/tools.test.ts` — `node:test` unit tests using a stub `fetch` (no network).
