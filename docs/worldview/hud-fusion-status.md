# HUD Fusion Status

## Status

Agent A has started and landed the first real Vite HUD integration path.

## Landed

- `frontend/src/modes_world.tsx`
  - Signal Layer status strip.
  - World brief.
  - Relevant signal list.
  - Evidence/freshness drawer.
  - Ask Argus / World Analyst panel.
  - Graceful unavailable state when `:8787` is not reachable.

- `frontend/src/world_app.tsx`
  - Wraps the existing HUD without refactoring the large app root.
  - Adds a fixed `WORLD` button and `W` hotkey.
  - Opens the World Intelligence cockpit as a full-screen overlay.

- `frontend/src/main.tsx`
  - Mounts `world_app` instead of raw `app`, preserving the existing app as the underlying HUD.

## Current CI state

Frontend tests and Vite build pass, but the `hud-v2-build` job fails at the committed-bundle check because `agents/web/v2` needs to be rebuilt and committed.

Required local command:

```bash
cd frontend
npm ci
npm run build
git add ../agents/web/v2 frontend/src/modes_world.tsx frontend/src/world_app.tsx frontend/src/main.tsx
git commit -m "build(worldview): refresh HUD v2 bundle for world intelligence"
```

## Why this integration path

The large HUD root is intentionally left untouched except for `main.tsx`. This keeps risk low while giving Sunday demo a visible product surface.

## Remaining Agent A work

1. Rebuild and commit `agents/web/v2` bundle.
2. Optionally move the `WORLD` entry point into the left rail after the bundle is stable.
3. Keep degraded Signal Layer states visible and honest.
