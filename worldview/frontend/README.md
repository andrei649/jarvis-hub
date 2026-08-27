# WorldView Frontend

CesiumJS + Vite + TypeScript, **no UI framework** — the God's Eye View build shape, wired to
WorldView's own 4D API. Renders the time-scrubbable 3D globe and synchronizes every layer from a
single Zustand **System Master Time** store.

## The basemap needs no account

Cesium ships Natural Earth II raster tiles inside the package. With **no token, no account and no
network fetch** the globe renders real continents, coastlines and bathymetry from those local
files (`plugins/cesium.ts` mirrors them into `public/`, `src/globe/imagery.ts` loads them). Set
`VITE_CESIUM_ION_TOKEN` to upgrade the same slot to ion world imagery (photographic) plus world
terrain (3D relief). The HUD's basemap line always states which one you are looking at.

## Develop

```bash
npm install                        # from the worldview/ monorepo root (workspaces)
cp .env.local.example .env.local   # optional: VITE_CESIUM_ION_TOKEN, VITE_API_URL
npm run dev --workspace frontend   # http://localhost:3000
```

Layer data needs backend-api running (REST `/history` + WebSocket `/live`); without it the globe
still renders and the HUD explains what's missing and how to start it.

```bash
npm run typecheck --workspace frontend
npm test --workspace frontend      # vitest, node env — no GPU needed
npm run build --workspace frontend
```

## How it fits together

```
index.html          sets window.CESIUM_BASE_URL, mounts #app
plugins/cesium.ts   mirrors Cesium's runtime assets into public/cesium (once per version)
src/main.ts         bootstrap: DOM shell, globe, controllers, HUD surfaces, drivers

src/globe/
  scene.ts          PURE: per-layer FeatureCollections → a plain draw spec (marks, polygons,
                    polylines, labels, tile overlay). Cesium-free, so layer selection and mark
                    encodings are unit-tested in node.
  render.ts         applies a draw spec to Cesium collections, diffed by id between frames
  viewer.ts         viewer construction; globe lighting bound to the MASTER clock, so scrubbing
                    time moves the day/night terminator with the data
  basemap.ts        PURE: which basemap this session draws, and the sentence the HUD prints
  imagery.ts        that decision as Cesium imagery layers (+ the raster tile overlay)
  camera.ts         fly-tos, the AOI tour, the follow lock, 2.5D ⇄ 3D, zoom feedback
  zoom.ts           PURE: camera height ⇄ slippy-map zoom (the LOD contract)
  sensors.ts        sensor grades (thermal / night / tactical) as post-process stages
  picking.ts        hover tooltip + click selection

src/app/            clock, data (REST as-of-T + live WebSocket), track, recon, tour, replay,
                    keyboard shortcuts — the drivers, all framework-free
src/ui/             direct-DOM HUD surfaces over a ~100-line render helper (dom.ts): app bar,
                    layer panel (= legend), recon, stats, inspector, alerts, export, timeline
                    (+ replay chip), system status, help, arrival banner, mode frame, overlays
src/lib/            the domain layer, unchanged across the renderer swap: layers, api, types,
                    markStyle, markIcons, negativeSpace, uiMode, inspectorFields, alerts,
                    timelineMarkers, recon, provenance, export, arrival, replaySchedule,
                    cameraTour, tiles, env, store/timelineStore
```

## Design

Per `docs/design/WORLDVIEW_UX_SPEC.md` (brand tokens, zone system, mode system, shape encodings,
negative-space grammar). The design is unchanged by the renderer swap — the spec's references to
the previous Deck.gl/Mapbox implementation are superseded by the modules above.

## Sensor grades

`V` cycles NORMAL → THERMAL → NIGHT → TACTICAL. These are **visual grades** applied to the
rendered frame by Cesium post-process stages — a thermal-looking picture is not thermal data, and
the HUD labels them as grades for exactly that reason.

## Note on dependency pins

`cesium` is pinned exactly. The keyless basemap depends on files inside the package
(`Assets/Textures/NaturalEarthII`), not on an API we call, so `src/globe/__tests__/cesiumAssets.test.ts`
asserts that contract at test time — an upgrade that moved those files would otherwise only show
up as a blank globe at runtime.
