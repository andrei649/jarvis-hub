# H130 reverse-proxy base path implementation plan

Goal: serve the same production HUD bundle at root or an operator-configured prefix,
including deep links, APIs, streams, lazy assets, PWA and linked map/mission-control.
Base SHA: 1ddd6c333a09e57a1c90462712bd7fc1477b65ef.
Generated: 2026-09-15. Verified working tree based on the base SHA above.
Next action: integrator review/publishing; source implementation and checks complete.
Spec: frozen H130 in docs/research/2026-09-07-hermes-absorption-ledger.json;
web-shell.base-path, index-injection and mount-spa in its frozen inventory.

Architecture: JARVIS_ROOT_PATH is validated static operator configuration read via
core.env_config, default empty. FastAPI root_path and an escaped bootstrap value
share that configuration. The frontend retains logical /v2 routes and translates
only public URLs. Vite emits relative assets; the server resolves entry tags.
No forwarded-prefix trust, native permission changes, new dependencies, live provider
calls, legacy-v1 prefix claim, credential injection or HTML base element.

- [x] Step 1: backend configuration and shell. Add core/web_base_path.py with
  normalize_root_path(value), configured_root_path(), render_ui_html(html, prefix).
  Wire FastAPI root_path and existing shell routes. Switch Vite base to './'.
  Red/green tests/test_web_base_path.py: invalid prefix, root/deep shell, forged
  header ignored, public asset paths and honest missing assets.
- [x] Step 2: frontend public URL boundary. Add base-path.ts with basePath(),
  appUrl(logicalPath), logicalPath(publicPath), internalLink(url). Router parsing
  stays logical; href/current-location adapters use these functions. Apply appUrl
  to client.ts and direct voice/tts/analytics/binary/SSE transports; internalLink
  to same-origin rendered artifacts and backend-provided destinations. Test
  prefix routing/history/demo/floating, fetch credentials/retry/stream and links.
- [x] Step 3: PWA and linked pages. Prefix manifest, icon, registration and scope;
  worker derives registration scope, isolates caches per prefix, caches only HUD
  assets/navigation shell. Preserve unrelated caches and never cache API data.
  Render system_map and mission_control through the shared bootstrap helper and
  prefix their fetch paths. Add Python and executable JS worker regressions.
- [x] Step 4: actual proxy acceptance. Start the real app without production
  lifespan in an isolated test process, expose it through a real HTTP proxy that
  strips an explicit prefix, and test the committed bundle in Chromium desktop
  and mobile. Only test-fixture services supply mutation/stream payloads. Verify
  root plus two prefixes use identical assets, deep reload/history/lazy fonts,
  demo/floating, API/SSE, manifest/offline/cache isolation and no root URL leaks.
  Run affected backend tests, full frontend suite with one worker, both typechecks,
  browser tests, native route-generator sync, and deterministic rebuild.

Relevant paths: agents/web.py; agents/core/web_base_path.py;
agents/core/routers/{system_map,swarm}.py; agents/web/{system_map,mission_control}.html;
frontend/{index.html,vite.config.ts,public,src,e2e,docs}; tests/test_web_base_path.py,
tests/test_pwa_v2.py,tests/test_web_asset_manifest_integrity.py; agents/web/v2 outputs.
Root integrator owns global ledgers/counts/publishing. No changes to protected paths.
Rollback: revert the coherent implementation commit(s) and generated bundle together.

## Operator guide

Set the prefix in the process environment before starting Python. It is fixed for
that process, not a live setting and not inferred from request headers:

```sh
JARVIS_ROOT_PATH=/nerva JARVIS_ALLOWED_HOSTS=nerva.example python serve.py
```

Empty (the default) or `/` keeps root hosting. `/nerva/` normalizes to `/nerva`;
nested prefixes such as `/tools/nerva` work. Each segment must use ASCII letters,
digits, `_`, `~`, `-` or `.`; empty segments, `.`/`..`, escaped separators, whitespace,
queries and fragments are rejected at boot. Use JARVIS_ROOT_PATH rather than an
independent Uvicorn `--root-path` override so all entry points share configuration.

Inside an existing TLS nginx server for `nerva.example`:

```nginx
location = /nerva { return 308 /nerva/; }
location /nerva/ {
    proxy_pass http://127.0.0.1:8080/;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_buffering off;
}
```

The trailing slash on `proxy_pass` strips `/nerva/`. Keep the backend loopback-only;
retain the existing allowed-host, authentication and proxy-trust configuration.
This feature does not grant trust to X-Forwarded-Prefix or widen native desktop
origins. Run the identical checked-in bundle at `/` or any configured prefix; no
frontend rebuild is needed when the deployment prefix changes. Direct Vite preview
is not the production shell renderer; use the Python app for deep-link verification.

The V2 shell, linked `/map` and `/mission-control`, requests, lazy assets and PWA
follow the prefix. Existing `/v1` remains available but is not claimed prefix-aware.
Signal Layer and external WorldView retain their own configured origins. Browser
origin remains the browser's trust boundary; path prefixes are deployment locations.
Service-worker cache names and deletion are isolated by deployment prefix, and APIs
and mutations remain network-only.

## Verification boundary

`frontend/e2e/support/base_path_server.py` serves the real app routes and committed
assets through an actual loopback HTTP proxy at root, `/one` and `/two/nerva`.
It disables lifespan/provider startup, uses temporary data roots, and supplies
fixture-only mutation/stream responses. Browser floating selection uses a mock
bridge; this is not native GUI or production deployment evidence.

Reproduce from frontend/ with available Python dependencies and Chromium:

```sh
NERVA_TEST_PYTHON=../.venv/bin/python node_modules/.bin/playwright test --config playwright.base-path.config.ts
```

Native desktop deployment uses the default empty JARVIS_ROOT_PATH. Its unchanged
allowlist accepts logical `/v2/...` paths at the exact local origin; nonempty
prefix hosting is supported in browsers, not by the current native wrapper.

Non-stripping proxies are unsupported: the backend must receive logical paths such
as `/v2/chat`, not `/nerva/v2/chat`. Do not combine this setting with Uvicorn's
`--root-path`; the app supplies the routing context and adds the public prefix at
its inner router boundary. Always prepending there also supports prefixes named
`/v2` or `/api` without confusing them with existing logical route segments.

The browser fixture additionally configures a test user token and sends
`POST /api/schedule/parse` through the actual app middleware and route: missing
credentials are refused, valid credentials produce the offline parser's expected
cron result. It creates no schedule. Synthetic chat/cognition frames remain
transport-only evidence; they do not prove those endpoints' authorization.


## Completed evidence (2026-09-15)

- Full frontend: **1,229/1,229 tests**, one Vitest worker. Actual delta: **13**
  (8 base-path, 3 worker, 2 overlay keyboard regressions).
- Backend affected suite: **146 passed** across base-path, PWA, asset integrity,
  HUD parity, map/export, swarm and orchestrator-binding checks. Actual new backend
  tests: **29** (28 base-path + 1 relative-preload missing-CSS regression).
- Both app and E2E TypeScript checks passed; native route generator sync passed.
- Production browser checks: **16 passed** (8 prefix/cohosting and 8 existing PWA
  tests across desktop Chrome and Pixel 7), plus **2 H129 routing smoke tests**.
  Prefix checks cover real guarded schedule-parse authorization and byte-identical
  entry assets, as well as lazy fonts/chunks, reload/history, keyboard closing,
  floating UI selection, linked pages, redirects, worker scopes and offline shells.
- Production rebuild: **16 files byte-identical** on a second build.
- Independent review reproduced and cleared console toggle, World Escape and
  `/v2`/`/api` prefix-collision regressions. No native-origin or policy change.

RED evidence was captured before fixes for missing server/bootstrap transport,
worker cache isolation, linked pages, relative preload resolution, framework
static mounts/redirects, invalid logical URL input, keyboard closing and prefix
collisions. Root/non-stripping/native and fixture boundaries are stated above.
