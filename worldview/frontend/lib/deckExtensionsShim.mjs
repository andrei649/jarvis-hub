// H19.5.1 build shim. MVTLayer (imported deep, see mvtLayer.ts) does
// `import { ClipExtension } from '@deck.gl/extensions'`. That barrel also pulls in the
// terrain extension, whose util does `@luma.gl/webgl` ./constants import that this repo's
// pinned luma version no longer exports — breaking `next build`. We webpack-alias the bare
// `@deck.gl/extensions` specifier (exact match only, via `$`) to this shim, which re-exports
// just ClipExtension straight from its clean dist module. Nothing in our actual layer graph
// uses any other extension, so this is sufficient and avoids the terrain → luma chain.
// `@deck.gl-clip-extension` is a webpack alias (next.config) pointing at the clean dist module;
// using an alias avoids the package `exports` gate that blocks the deep subpath.
export { default as ClipExtension } from "@deck.gl-clip-extension";
