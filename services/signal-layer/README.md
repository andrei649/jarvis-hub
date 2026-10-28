# Signal Layer

The optional local HTTP service provides evidence, signals, assessments and briefs.
It is independent of the retired WorldView stack. Replay is the default; it does
not prove live provider access or collection.

Run directly with Node 20 or newer:

```sh
cd services/signal-layer
npm start
```

The hub's launchers start it only when `JARVIS_SIGNAL_LAYER=1` is explicitly set.
Health is available at `http://127.0.0.1:8787/healthz`.

Configuration:

- `JARVIS_SIGNAL_LAYER_MODE`: `replay` by default; `live` selects the external provider.
- `SIGNAL_LAYER_HOST` / `SIGNAL_LAYER_PORT`: default `127.0.0.1` / `8787`.
- `SIGNAL_LAYER_API_TOKEN`: optional bearer authentication. A nonlocal bind must
  be an explicit operator decision; use authentication before exposing the service.
- `WORLDMONITOR_BASE_URL` / `WORLDMONITOR_MCP_URL`: default local sidecar at port 3100.
  Live mode requires a separately configured, reachable provider.

Retired WorldView environment variables do not configure this service.
Run `npm test` for deterministic configuration, replay, auth and mock-provider
contracts. These tests do not claim a successful live WorldMonitor deployment.
