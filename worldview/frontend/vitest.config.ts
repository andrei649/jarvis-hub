import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";

// Pure-logic unit tests (store, API client, layer registry, scene builder). No DOM/WebGL and no
// Cesium import: src/globe/scene.ts deliberately produces a plain draw-spec that the Cesium
// renderer consumes, so the map's layer selection stays testable in a node environment.
// The `@/` alias mirrors tsconfig paths so source modules resolve under vitest.
const src = fileURLToPath(new URL("./src", import.meta.url)).replace(/\/$/, "");

export default defineConfig({
  resolve: {
    alias: { "@": src },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
