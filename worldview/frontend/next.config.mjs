import { fileURLToPath } from "node:url";
import path from "node:path";

const here = path.dirname(fileURLToPath(import.meta.url));

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // The application package and its node_modules live at worldview/, not the
  // enclosing JARVIS repository whose lockfile Next 16 otherwise discovers first.
  outputFileTracingRoot: path.resolve(here, ".."),
  // deck.gl / luma.gl ship ESM; transpile for Next's bundler.
  transpilePackages: ["@deck.gl/core", "@deck.gl/layers", "@deck.gl/geo-layers", "@deck.gl/mapbox", "@deck.gl/react"],
  webpack: (config) => {
    // Next 16.2 may infer the repository-level package-lock as the workspace root.
    // Keep the frontend's @/ imports anchored here instead of resolving them from the
    // enclosing JARVIS workspace.
    config.resolve.alias["@"] = here;
    // H19.5.1: import MVTLayer straight from its dist module, bypassing the
    // "@deck.gl/geo-layers" barrel. The barrel re-exports Tile3DLayer → @deck.gl/mesh-layers,
    // which (against this repo's pinned core/luma versions) imports `phongMaterial` from
    // @deck.gl/core where it no longer exists, breaking `next build`. MVTLayer itself doesn't
    // touch mesh-layers, so the deep import is safe. Keep this alias in sync with the tsconfig
    // `@deck.gl-mvt-layer` path.
    config.resolve.alias["@deck.gl-mvt-layer"] = path.resolve(
      here,
      "../node_modules/@deck.gl/geo-layers/dist/mvt-layer/mvt-layer.js",
    );
    // MVTLayer pulls ClipExtension from the @deck.gl/extensions barrel, which also drags in the
    // terrain extension → @luma.gl/webgl ./constants (not exported by the pinned luma), failing
    // the build. Alias the bare specifier (exact `$`) to a shim that re-exports only
    // ClipExtension from its clean dist module. Subpath imports are unaffected.
    config.resolve.alias["@deck.gl/extensions$"] = path.resolve(here, "lib/deckExtensionsShim.mjs");
    config.resolve.alias["@deck.gl-clip-extension"] = path.resolve(
      here,
      "../node_modules/@deck.gl/extensions/dist/clip/clip-extension.js",
    );
    return config;
  },
};

export default nextConfig;
