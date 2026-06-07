import { defineConfig } from "vitest/config";
import { fileURLToPath } from "node:url";

// Pure-logic unit tests (store, API client, layer registry). No DOM/WebGL needed.
// The `@/` alias mirrors tsconfig paths so source modules resolve under vitest.
const root = fileURLToPath(new URL(".", import.meta.url)).replace(/\/$/, "");

export default defineConfig({
  resolve: {
    alias: { "@": root },
  },
  test: {
    environment: "node",
    include: ["lib/**/*.test.ts"],
  },
});
