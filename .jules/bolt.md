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

## 2026-04-03 - Per-frame Map Allocations and Array Slices in Canvas Task Fan Loops
**Learning:** In Canvas 2D components (`NeuralMesh` in `frontend/src/mesh.tsx`), helper functions in `draw()` like `drawTaskFan()` allocated a `new Map()` and `.slice()` array copies on every 60 FPS frame (~3,600 allocations/min). In addition, `taskColor()` created single-element `[t]` arrays to call `runningTasks([t])`.
**Action:** Pre-group tasks on the state ref (`S.current.tasksByOwner`) inside `useEffect` on task state changes, and evaluate task status directly (`task.state === 'running'`) to achieve zero allocations during frame rendering.

## 2026-04-04 - High-frequency Array Iteration Closures in Canvas Animation Loops
**Learning:** In canvas components like `NeuralBurst` (`frontend/src/burst.tsx`), nested `.forEach()` calls across cluster dendrites and synapse nodes execute ~500+ times per frame (~30,000 callback closures/sec at 60 FPS). This causes function closure allocation overhead and CPU cycle overhead in main-thread frame rendering.
**Action:** Use indexed `for` loops (`for (let i = 0; i < len; i++)`) in Canvas 2D `draw()` animation loops to avoid closure creation overhead entirely.

## 2026-04-05 - Frame-throttling MutationObserver Layout Measurements in HUD Overlays
**Learning:** `MutationObserver` watching `document.body` for subtree changes (such as in `PointerView` in `frontend/src/pointer.tsx`) fires synchronously on microtask DOM updates. Calling `elementFromPoint()` or `getBoundingClientRect()` directly inside the mutation callback forces synchronous layout recalculations (layout thrashing) on every DOM mutation burst.
**Action:** Frame-throttle DOM layout measurement callbacks triggered by `MutationObserver` using `requestAnimationFrame` to collapse mutation bursts into at most one layout measurement per animation frame.
