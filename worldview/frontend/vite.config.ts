import { defineConfig } from "vite";
import { fileURLToPath } from "node:url";
import tailwindcss from "@tailwindcss/vite";
import { cesiumAssets } from "./plugins/cesium";

// WorldView frontend — Vite + CesiumJS, no framework (the God's Eye View build shape).
//
// `cesiumAssets` mirrors Cesium's runtime assets into public/, which is what makes the
// token-less basemap possible: Cesium ships Natural Earth II tiles under Assets/Textures, so the
// globe renders a real Earth with no account, no key and no network fetch (src/globe/imagery.ts).
const src = fileURLToPath(new URL("./src", import.meta.url)).replace(/\/$/, "");

export default defineConfig({
  plugins: [cesiumAssets(), tailwindcss()],
  resolve: {
    alias: { "@": src },
  },
  server: { port: 3000 },
  preview: { port: 3000 },
  build: {
    // Cesium is a large single dependency; the default 500 kB warning is pure noise here.
    chunkSizeWarningLimit: 4096,
  },
});
