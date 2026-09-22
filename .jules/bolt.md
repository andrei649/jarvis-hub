# Bolt's Journal - Critical Learnings

## 2026-03-31 - Canvas Animation Loop O(N) Lookups in NeuralMesh
**Learning:** Canvas 2D components driven by `requestAnimationFrame` (e.g. `NeuralMesh` in `frontend/src/mesh.tsx`) execute `draw()` at 60-120 FPS. Helper functions like `node(id)` that search arrays (`st.nodes.find(...)`) cause hundreds of O(N) array scans per frame for every edge, particle, and task fan line.
**Action:** Always maintain an O(1) `Map` lookup index (e.g. `st.nodeMap = new Map(...)`) on the state ref when building or updating canvas elements so frame rendering stays O(1) per lookup.

## 2026-04-01 - Per-frame Heap Allocations in Canvas Particle Animation Loops
**Learning:** In canvas particle spheres or animation components driven by `requestAnimationFrame` (e.g., `VoiceOrb` in `frontend/src/orb.tsx`), constructing new objects inside `.forEach()` (such as `proj.push({ x, y, d })`) allocates 620+ objects per frame (~37,200 allocations/sec at 60 FPS). This causes main-thread GC pressure and frame stuttering.
**Action:** Pre-allocate projection object arrays on the component ref (`st.proj`) and mutate fields in-place inside indexed `for` loops to achieve zero allocations per frame.

## 2026-04-02 - Per-frame Canvas Text Layout Measurements (ctx.measureText) and O(N*M) Roster Scans
**Learning:** Calling `ctx.measureText()` inside Canvas 2D `requestAnimationFrame` loops at 60 FPS triggers browser font layout engine calculations on every frame. Additionally, resolving task-to-tier mappings via nested `Array.includes()` scans creates O(Tasks * Tiers * Agents) work on state updates.
**Action:** Cache `ctx.measureText` results on cluster/node state objects until text strings actually change, and build an `agentToTier` `Map` during roster indexing to keep task resolution O(1).
