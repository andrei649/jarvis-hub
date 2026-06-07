// WorldView MCP server (ticket H19.3.1).
//
// Exposes the WorldView 4D OSINT REST API (`@worldview/backend-api`) as Model Context Protocol
// tools over **stdio**, so an MCP client — e.g. the JARVIS agent system — can query the platform.
//
// We use the SDK's low-level `Server` + `setRequestHandler` API (rather than the high-level
// `McpServer.registerTool`) so we can declare tool inputs as plain JSON Schema, keeping this
// package free of a direct Zod dependency and matching the backend's JSON contract 1:1.
//
// Wiring: each tool's `call` delegates to a pure handler in `./tools.ts`, injecting the configured
// backend URL and the global `fetch`. The handlers return `{ content: [{type:"text", text}], isError? }`,
// which is exactly the MCP `CallToolResult` shape, so we can forward them verbatim.

import { pathToFileURL } from "node:url";

import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import {
  CallToolRequestSchema,
  ListToolsRequestSchema,
  type CallToolResult,
  type Tool,
} from "@modelcontextprotocol/sdk/types.js";

import { apiUrl, mcpSecret } from "./config.js";
import { audit, verifyCapability, type AuditSink } from "./auth.js";
import {
  LAYERS,
  RECONSTRUCT_EVENT_SCOPE,
  TRACK_LAYERS,
  WATCH_AOI_SCOPE,
  findDarkVessels,
  listLayers,
  reconstructEvent,
  stateAt,
  trackOf,
  watchAoi,
  type Deps,
  type FindDarkVesselsArgs,
  type ReconstructEventArgs,
  type StateAtArgs,
  type ToolResult,
  type TrackOfArgs,
  type WatchAoiArgs,
} from "./tools.js";

// Dependencies handed to every pure handler. `fetch` is global in Node >= 18.
const deps: Deps = { apiUrl, fetchImpl: fetch };

// --- Tool declarations (JSON Schema input definitions) ----------------------

const TOOLS: Tool[] = [
  {
    name: "state_at",
    description:
      "As-of-T reconstruction of one WorldView layer at a unix timestamp. Returns a GeoJSON " +
      "FeatureCollection of every entity present at time t (optionally clipped to a bounding box).",
    inputSchema: {
      type: "object",
      properties: {
        layer: {
          type: "string",
          enum: [...LAYERS],
          description: "Which 4D layer to reconstruct (adsb, ais, tle, ew, context).",
        },
        t: {
          type: "number",
          description: "The instant to reconstruct, as unix seconds.",
        },
        bbox: {
          type: "string",
          description: "Optional viewport filter as 'w,s,e,n' (WGS84 degrees).",
        },
        lod: {
          type: "string",
          enum: ["raw", "minute"],
          description: "Level of detail: 'raw' points (default) or 'minute' rollups.",
        },
      },
      required: ["layer", "t"],
    },
  },
  {
    name: "find_dark_vessels",
    description:
      "Find 'dark vessels' (vessels with suspicious AIS gaps) at time t. Pulls the derived " +
      "'context' layer and returns only the dark-vessel detections as a GeoJSON FeatureCollection.",
    inputSchema: {
      type: "object",
      properties: {
        t: { type: "number", description: "The instant to inspect, as unix seconds." },
        bbox: {
          type: "string",
          description: "Optional viewport filter as 'w,s,e,n' (WGS84 degrees).",
        },
      },
      required: ["t"],
    },
  },
  {
    name: "track_of",
    description:
      "Retrieve one entity's movement trail as a GeoJSON LineString FeatureCollection. " +
      "Tracks exist only for the adsb/ais/tle layers; from/to default to the trailing hour.",
    inputSchema: {
      type: "object",
      properties: {
        layer: {
          type: "string",
          enum: [...TRACK_LAYERS],
          description: "Trackable layer (adsb, ais, tle).",
        },
        entityId: {
          type: "string",
          description: "Entity identifier (e.g. ICAO hex for adsb, MMSI for ais, NORAD id for tle).",
        },
        from: { type: "number", description: "Optional start of the window, unix seconds." },
        to: { type: "number", description: "Optional end of the window, unix seconds." },
      },
      required: ["layer", "entityId"],
    },
  },
  {
    name: "list_layers",
    description:
      "List the available WorldView 4D layers with a one-line description of each. No arguments.",
    inputSchema: { type: "object", properties: {} },
  },
  // --- WRITE / async tools (capability-gated) --------------------------------
  // Both require a scoped capability token (the `token` property below); the server verifies it
  // BEFORE the side effect (see `dispatch`). An unauthorised call is rejected and audited.
  {
    name: "watch_aoi",
    description:
      "WRITE (scope 'worldview:watch'): create a standing watch rule for an area of interest. " +
      "Requires a capability token scoped for 'worldview:watch'; unauthorised calls are rejected " +
      "and audited. Posts the rule to the backend and returns a summary of the created watch.",
    inputSchema: {
      type: "object",
      properties: {
        aoiId: { type: "string", description: "Identifier of the area of interest to watch." },
        rule: {
          type: "string",
          description: "The watch rule/expression to evaluate against the AOI (e.g. a trigger).",
        },
        lead: {
          type: "number",
          description: "Optional lead time in seconds for the watch to fire early.",
        },
        token: {
          type: "string",
          description: "Capability token (HMAC-signed) granting the 'worldview:watch' scope.",
        },
      },
      required: ["aoiId", "rule", "token"],
    },
  },
  {
    name: "reconstruct_event",
    description:
      "WRITE/async (scope 'worldview:reconstruct'): request a bounded reconstruction/replay over a " +
      "time window. Requires a capability token scoped for 'worldview:reconstruct'; unauthorised " +
      "calls are rejected and audited. Kicks off the job and returns a handle the caller can poll.",
    inputSchema: {
      type: "object",
      properties: {
        from: { type: "number", description: "Start of the window to reconstruct, unix seconds." },
        to: { type: "number", description: "End of the window to reconstruct, unix seconds." },
        bbox: {
          type: "string",
          description: "Optional viewport filter as 'w,s,e,n' (WGS84 degrees).",
        },
        layers: {
          type: "array",
          items: { type: "string", enum: [...LAYERS] },
          description: "Optional subset of 4D layers to reconstruct; defaults to all.",
        },
        token: {
          type: "string",
          description: "Capability token (HMAC-signed) granting the 'worldview:reconstruct' scope.",
        },
      },
      required: ["from", "to", "token"],
    },
  },
];

// --- Auth gate for WRITE tools ----------------------------------------------

/** Map each WRITE tool to the capability scope a token must grant to invoke it. */
export const WRITE_SCOPES: Record<string, string> = {
  watch_aoi: WATCH_AOI_SCOPE,
  reconstruct_event: RECONSTRUCT_EVENT_SCOPE,
};

/** Injectable knobs for the auth gate; defaults wire the module config + stderr audit sink. */
export interface AuthGateOpts {
  /** HMAC secret to verify the token against (default: `mcpSecret` from config). */
  secret?: string | undefined;
  /** Audit sink for the allow/deny line (default: `audit`'s built-in stderr sink). */
  auditSink?: AuditSink;
  /** Current time as unix seconds (default: real clock inside `verifyCapability`). */
  now?: number;
}

/**
 * Enforce the capability check for a WRITE tool BEFORE its side effect. Extracts the `token` arg,
 * verifies it against the required scope (constant-time, fail-closed on a missing secret/token),
 * audits the allow/deny decision to STDERR, and only invokes `run` on success. On denial we return
 * an error `ToolResult` and NEVER touch the backend. `audit`'s default sink is `process.stderr`;
 * the secret/sink/now are injectable so the gate is unit-testable.
 */
export async function authorizeWrite(
  tool: string,
  requiredScope: string,
  args: Record<string, unknown>,
  run: () => Promise<ToolResult>,
  opts: AuthGateOpts = {},
): Promise<ToolResult> {
  const secret = opts.secret !== undefined ? opts.secret : mcpSecret;
  const token = typeof args.token === "string" ? args.token : undefined;
  const verdict = verifyCapability(token, requiredScope, { secret, now: opts.now });
  if (!verdict.ok) {
    audit({ tool, decision: "deny", reason: verdict.reason }, opts.auditSink);
    return {
      content: [
        {
          type: "text",
          text: `UNAUTHORIZED: '${tool}' requires a capability token scoped for '${requiredScope}' (${verdict.reason}).`,
        },
      ],
      isError: true,
    };
  }
  audit({ tool, decision: "allow", sub: verdict.claims.sub }, opts.auditSink);
  return run();
}

// --- Dispatch: tool name -> pure handler ------------------------------------

async function dispatch(name: string, args: Record<string, unknown>): Promise<ToolResult> {
  switch (name) {
    case "state_at":
      return stateAt(args as unknown as StateAtArgs, deps);
    case "find_dark_vessels":
      return findDarkVessels(args as unknown as FindDarkVesselsArgs, deps);
    case "track_of":
      return trackOf(args as unknown as TrackOfArgs, deps);
    case "list_layers":
      return listLayers();
    // WRITE/scoped tools: auth is enforced before the side-effecting handler runs.
    case "watch_aoi":
      return authorizeWrite(name, WRITE_SCOPES[name]!, args, () =>
        watchAoi(args as unknown as WatchAoiArgs, deps),
      );
    case "reconstruct_event":
      return authorizeWrite(name, WRITE_SCOPES[name]!, args, () =>
        reconstructEvent(args as unknown as ReconstructEventArgs, deps),
      );
    default:
      return {
        content: [{ type: "text", text: `Unknown tool '${name}'.` }],
        isError: true,
      };
  }
}

// --- Server bootstrap -------------------------------------------------------

const server = new Server(
  { name: "@worldview/mcp", version: "0.1.0" },
  { capabilities: { tools: {} } },
);

server.setRequestHandler(ListToolsRequestSchema, async () => ({ tools: TOOLS }));

server.setRequestHandler(CallToolRequestSchema, async (request): Promise<CallToolResult> => {
  const { name, arguments: args } = request.params;
  const result = await dispatch(name, args ?? {});
  // `ToolResult` is structurally a `CallToolResult` (text content blocks + optional isError);
  // the SDK's broader union also admits a task-result variant we never produce.
  return result as CallToolResult;
});

export async function main(): Promise<void> {
  const transport = new StdioServerTransport();
  await server.connect(transport);
  // Stay silent on stdout (reserved for the JSON-RPC stream); log to stderr only.
  process.stderr.write(`worldview-mcp connected over stdio (backend: ${apiUrl})\n`);
}

// Only boot the stdio transport when run as the process entrypoint (the `worldview-mcp` bin), not
// when imported — e.g. by the unit tests, which exercise `authorizeWrite`/`dispatch` directly and
// must NOT connect stdio. Guard via argv[1] so importing this module stays side-effect-free.
const invokedDirectly =
  typeof process.argv[1] === "string" &&
  import.meta.url === pathToFileURL(process.argv[1]).href;

if (invokedDirectly) {
  main().catch((e: unknown) => {
    process.stderr.write(`worldview-mcp failed to start: ${(e as Error).message}\n`);
    process.exit(1);
  });
}
