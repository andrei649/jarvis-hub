// Runtime configuration, read at CALL TIME from whichever env bag exists.
//
// Vite exposes build-time `VITE_*` vars on `import.meta.env`; node (vitest, any tooling) has
// `process.env`. Reading both — process first, so `vi.stubEnv` in a test wins — keeps every
// consumer (`api`, `tiles`, `recon`, …) testable without a bundler and identical in the browser.
// Nothing here throws: a missing var is just its fallback.

type EnvBag = Record<string, string | undefined>;

function bags(): EnvBag[] {
  const out: EnvBag[] = [];
  if (typeof process !== "undefined" && process.env) out.push(process.env as EnvBag);
  const meta = (import.meta as unknown as { env?: EnvBag }).env;
  if (meta) out.push(meta);
  return out;
}

/** The raw value of `name`, or `fallback` when unset/blank in every bag. */
export function env(name: string, fallback = ""): string {
  for (const bag of bags()) {
    const value = bag[name];
    if (typeof value === "string" && value.trim() !== "") return value;
  }
  return fallback;
}

/** The WorldView REST API base (Fastify `/history`, `/recon`, `/export`, `/provenance`). */
export function apiUrl(): string {
  return env("VITE_API_URL", "http://localhost:4000");
}

/** The live WebSocket endpoint (snapshot + deltas). */
export function wsUrl(): string {
  return env("VITE_WS_URL", "ws://localhost:4000/live");
}
