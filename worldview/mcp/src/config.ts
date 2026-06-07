// Base URL of the WorldView backend REST API (the Fastify `@worldview/backend-api` service).
// Override with WORLDVIEW_API_URL; defaults to the local dev backend.
export const apiUrl: string = process.env.WORLDVIEW_API_URL ?? "http://localhost:4000";

// HMAC secret used to verify capability tokens on WRITE/async tools (ticket H19.3.2).
//
// There is intentionally NO default: if `WORLDVIEW_MCP_SECRET` is unset, `mcpSecret` is undefined
// and every capability check FAILS CLOSED (write tools are rejected and audited as denied). In
// production JARVIS shares this secret with its CapabilityBroker, which mints the signed tokens.
export const mcpSecret: string | undefined = process.env.WORLDVIEW_MCP_SECRET;
