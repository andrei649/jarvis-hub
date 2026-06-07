// Base URL of the WorldView backend REST API (the Fastify `@worldview/backend-api` service).
// Override with WORLDVIEW_API_URL; defaults to the local dev backend.
export const apiUrl: string = process.env.WORLDVIEW_API_URL ?? "http://localhost:4000";
