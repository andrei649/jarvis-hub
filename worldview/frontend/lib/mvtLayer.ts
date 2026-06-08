// H19.5.1 — isolated MVTLayer import.
//
// We import MVTLayer from its dist subpath rather than the "@deck.gl/geo-layers" barrel on
// purpose. The barrel (index.js) also re-exports Tile3DLayer → @deck.gl/mesh-layers, which —
// against this repo's pinned @deck.gl/core / luma.gl versions (root `overrides`) — does an
// `import { phongMaterial } from '@deck.gl/core'` that no longer exists, breaking `next build`
// with "'phongMaterial' is not exported from '@deck.gl/core'". MVTLayer itself only depends on
// TileLayer + GeoJsonLayer + ClipExtension, none of which touch mesh-layers, so importing the
// module directly sidesteps the broken transitive import without changing any deck/luma deps.
//
// Keeping this in one tiny module means deckLayers.ts imports a clean local symbol and the
// workaround is documented in exactly one place.
// The `@deck.gl-mvt-layer` specifier is aliased (tsconfig `paths` + next.config webpack alias)
// straight to the package's dist MVTLayer module, bypassing the package `exports` gate that
// would otherwise force resolution through the broken barrel.
import MVTLayer from "@deck.gl-mvt-layer";

export { MVTLayer };
