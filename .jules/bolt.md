# Bolt's Journal - Critical Learnings

## 2026-03-31 - Canvas Animation Loop O(N) Lookups in NeuralMesh
**Learning:** Canvas 2D components driven by `requestAnimationFrame` (e.g. `NeuralMesh` in `frontend/src/mesh.tsx`) execute `draw()` at 60-120 FPS. Helper functions like `node(id)` that search arrays (`st.nodes.find(...)`) cause hundreds of O(N) array scans per frame for every edge, particle, and task fan line.
**Action:** Always maintain an O(1) `Map` lookup index (e.g. `st.nodeMap = new Map(...)`) on the state ref when building or updating canvas elements so frame rendering stays O(1) per lookup.
