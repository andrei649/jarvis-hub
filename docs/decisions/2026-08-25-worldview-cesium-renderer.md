# Decision — WorldView's frontend moves to CesiumJS, in the God's Eye View shape

> **Status: IMPLEMENTED** on branch `claude/gods-eye-view-atlas-replacement-kmjpp8`.
> Requested by the owner: *"replace it with God's Eye View"* — after the alternatives (basemap-only
> swap, vendoring upstream alongside) were put to him and declined in favour of a full replacement
> of `worldview/frontend`, on **Cesium ion** rather than Google Photorealistic 3D Tiles.

## The question

The owner asked whether [`bilawalsidhu/gods-eye-view`](https://github.com/bilawalsidhu/gods-eye-view)
(MIT) could replace the `world-atlas` npm package. It could not: `world-atlas` was a 55 KB Natural
Earth TopoJSON file imported by one module (`lib/landLayer.ts`) to draw a flat dark landmass under
the Deck.gl layers; God's Eye View is a 143-module, ~91 kLOC CesiumJS application. Told that, the
owner asked for the replacement anyway, at the largest of the three scopes offered.

## What "replace with God's Eye View" means here — and what it does not

Dropping the upstream app in verbatim would have deleted WorldView's actual differentiator. God's
Eye View is **live-only**, wired straight to public feeds (OpenSky, AISStream) with no notion of a
time-scrubbable history; WorldView's whole thesis is the Kafka → TimescaleDB → as-of-T API that
makes any moment in the last 24 h reconstructible. It also carries an OpenAI Realtime voice stack
this repo has no use for (it has its own).

So the frontend was **rebuilt in God's Eye View's shape** — its build shape (Vite + CesiumJS, no UI
framework, direct DOM), its rendering model (a 3D globe with true altitudes), and the capabilities
Cesium makes cheap that Deck.gl could not do (sensor grades, follow cam, sun-lit terminator) —
**wired to WorldView's own 4D API**, with every WorldView differentiator ported across. No upstream
source is vendored; the attribution is recorded in `.github/third-party-manifest.json` under
`untracked`, and `worldview/README.md` has always credited the project as the inspiration.

## What changed

| Before | After |
| --- | --- |
| Next.js 16 + React 19 + Deck.gl 9.3 + Mapbox GL | Vite + TypeScript + CesiumJS, no UI framework |
| `world-atlas` 110 m TopoJSON drawn as flat land | Cesium's bundled Natural Earth II raster tiles |
| Mapbox token needed for a real basemap | **no account needed at all**; ion token is an upgrade |
| 19 React components | 14 direct-DOM surfaces over a ~100-line render helper (`src/ui/dom.ts`) |
| Marks flat on a 2.5D map | Marks at true altitude (ADS-B and satellite geometries are `PointZ`) |
| Static lighting | Globe lighting bound to the master clock — scrubbing moves the terminator |

Ported unchanged in behaviour: the System Master Time store and clock, live WebSocket + historical
as-of-T fetching, per-layer status, entity trails, dark-vessel alerts, the negative-space grammar
(ghost / dead-reckoned path / uncertainty cone / captions), Inspector + provenance, export, recon
windows, camera tours, arrival deep links, the deterministic replay driver, the mode system, the
zone layout, keyboard shortcuts and the demo lens.

Added because Cesium makes them cheap: sensor grades (thermal / night / tactical, as post-process
stages — **visual grades, never a claim about the data**, and the HUD says so), a follow cam
(`F`), and the terminator binding above.

## Consequences accepted

- **Vector tiles are no longer drawable.** Cesium's imagery pipeline has no MVT decoder, so
  `VITE_TILE_URL` now accepts **raster** templates only; a `.pbf` template is refused by
  `src/lib/tiles.ts` and the globe keeps per-point rendering rather than silently showing nothing.
  The 1M-point acceptance criterion needs a raster endpoint in front of Martin
  (`worldview/deploy/README.md` §3).
- **Bundle size.** ~4.2 MB JS (1.1 MB gzipped) — Cesium is one large dependency. Unavoidable on
  this renderer, and the same figure God's Eye View ships.
- **Keyless basemap is low-resolution.** Natural Earth II is a global texture; zoomed in past a
  regional view it is visibly soft. This is stated in the HUD's basemap line rather than hidden,
  with the exact env var that fixes it.
- **Env vars renamed** `NEXT_PUBLIC_*` → `VITE_*` (a Vite requirement), across
  `.env.local.example`, `docker-compose.app.yml`, the Dockerfile and the deploy docs.
- **`NEXT_PUBLIC_MAPBOX_ACCESS_TOKEN` is gone**, and with it the Mapbox dependency.

## Rollback

One revert of the branch's merge commit. The change is confined to `worldview/frontend/**` plus the
env/doc references listed above; no backend, schema, ingestion or JARVIS-side contract changed, so a
revert restores the previous dashboard without touching data.

## Verification

`npm run typecheck`, `npm test` (157 tests, 19 files) and `npm run build` in the frontend workspace,
plus a headless-Chromium run of the built app against a fixture API: globe renders, all five layers
draw with correct counts, arrival deep link enters REPLAY with the banner, Inspector shows
provenance, recon/alerts/stats panels populate, sensor grade switches. Screenshots in the PR.
