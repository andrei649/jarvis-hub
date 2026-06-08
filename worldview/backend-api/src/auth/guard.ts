import type { FastifyInstance, FastifyReply, FastifyRequest } from "fastify";
import { config } from "../config.js";
import { verifyToken } from "./jwt.js";
import { AOI_WILDCARD, can, ruleFor, type Principal } from "./rbac.js";

// The request guard (ticket H19.4.2) — registered ONCE in server.ts, it authenticates + authorizes
// every request centrally (no scattered per-route checks) and decorates `request.principal` so
// handlers can apply ABAC AOI scoping. Two modes:
//   * DISABLED (config.authSecret === "", the default) — back-compat: no auth is enforced and every
//     request gets a permissive admin/`*` principal, so existing route tests + the `integration` CI
//     job (which set no secret) behave exactly as before.
//   * ENABLED (config.authSecret set) — fail-CLOSED: a missing/blank/invalid bearer is 401, and a
//     valid token lacking the route's required permission is 403. The token is an HS256 bearer
//     verified against authSecret (an external OIDC provider mints them in production).

// Augment Fastify's request with the resolved principal. Handlers read `request.principal` to filter.
declare module "fastify" {
  interface FastifyRequest {
    principal: Principal;
  }
}

// The permissive principal used in DISABLED mode (and only there): full admin, unrestricted AOI scope,
// so handlers that consult `request.principal` behave as open as the pre-auth code did.
const OPEN_PRINCIPAL: Principal = { sub: "anonymous", role: "admin", aois: [AOI_WILDCARD] };

// Pull the bearer token out of the Authorization header (case-insensitive scheme), or null. Guarded
// against a non-string / array header value.
function bearerOf(req: FastifyRequest): string | null {
  const raw = req.headers["authorization"];
  if (typeof raw !== "string") return null;
  const m = /^Bearer[ ]+(.+)$/i.exec(raw.trim());
  if (!m) return null;
  const token = m[1]!.trim();
  return token.length > 0 ? token : null;
}

/**
 * Register the auth guard on `app`. Decorates `request.principal` and installs ONE onRequest hook
 * that, when auth is enabled, authenticates the bearer + authorizes against the route's required
 * permission (replying 401/403 on failure) and resolves the principal's AOI scope. When disabled it's
 * a no-op that sets the open admin principal. Routes with no rule (e.g. /health, /ready) are public.
 */
export async function registerGuard(app: FastifyInstance): Promise<void> {
  const secret = config.authSecret;
  const enabled = secret.length > 0;

  // Decorate so `request.principal` is a known property (and typed); default to the open principal.
  app.decorateRequest("principal", null);

  app.addHook("onRequest", async (req: FastifyRequest, reply: FastifyReply) => {
    if (!enabled) {
      // Back-compat open mode: permissive principal, no enforcement.
      req.principal = OPEN_PRINCIPAL;
      return;
    }

    // Fastify resolves the matched route's pattern on req.routeOptions.url (v4). Fall back to the raw
    // url so an unmatched path is treated as having no rule (public) rather than crashing.
    const routerPath = req.routeOptions?.url ?? req.url.split("?")[0] ?? req.url;
    const rule = ruleFor(req.method, routerPath);

    // No rule ⇒ public route (e.g. /health, /ready). Still set a principal for any handler that reads
    // it, but don't require a token.
    if (!rule) {
      req.principal = OPEN_PRINCIPAL;
      return;
    }

    // Enabled + protected route ⇒ require a valid bearer (fail-CLOSED on missing/blank/invalid).
    const token = bearerOf(req);
    if (!token) {
      return reply.code(401).send({ error: "authentication required", reason: "missing bearer token" });
    }
    const result = verifyToken(token, secret);
    if (!result.ok) {
      return reply.code(401).send({ error: "authentication failed", reason: result.reason });
    }

    const claims = result.claims;
    // Resolve the AOI scope: omitted aois ⇒ unrestricted (treated as `*`), matching the claim shape.
    const aois = claims.aois && claims.aois.length > 0 ? claims.aois : [AOI_WILDCARD];
    const principal: Principal = { sub: claims.sub, role: claims.role, aois };
    req.principal = principal;

    // RBAC: the role must hold the route's required permission, else 403.
    if (!can(principal.role, rule.permission)) {
      return reply.code(403).send({
        error: "forbidden",
        reason: `role '${principal.role}' lacks permission '${rule.permission}'`,
      });
    }
    // ABAC AOI scoping (for scope-bearing routes) is applied inside the handlers via request.principal.
  });
}
